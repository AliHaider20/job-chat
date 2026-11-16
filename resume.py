"""Resume generator: LLM → structured Markdown → one-page ATS-friendly .docx.

The LLM returns a resume in a strict Markdown format; this module renders it in
the candidate's house layout (tight margins, SKILLS first, right-aligned dates,
no tables/text boxes/images), then checks the result against the job
description and asks the model to repair it when it falls short:

* page count must be 1 (measured with LibreOffice when installed, else estimated)
* every JD keyword the candidate honestly has must appear (>= 90%)
* no JD keyword the candidate does NOT have may appear (no fabrication)
* no leftover [ADD METRIC] placeholders or markdown noise
"""

import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config import PROJECT_ROOT
from observability import get_callbacks

logger = logging.getLogger(__name__)

# Free model with 131K context — handles the full profile+JD prompt reliably.
# The default openrouter/free model silently returns empty content for large prompts.
# Override with the RESUME_MODEL env var (a non-reasoning model is faster and never returns empty).
RESUME_MODEL = os.getenv("RESUME_MODEL", "nvidia/nemotron-3.5-lightning:free")

MAX_ATTEMPTS = 3
COVERAGE_TARGET = 0.9

_SKILLS_DIR = PROJECT_ROOT / "skills"
_FONT = "Times New Roman"
_BLACK = RGBColor(0, 0, 0)
_LINK = RGBColor(0x05, 0x63, 0xC1)

# Geometry copied from the reference resume template (Letter, one page).
_MARGIN_TB = Inches(0.34)
_MARGIN_LR = Inches(0.44)
_TEXT_WIDTH = Inches(7.62)
_LINE = Pt(12)  # exact line height of body text (0.1665in)
_BULLET_INDENT = Inches(0.2154)
_BULLET_HANG = Inches(0.1319)


def _load_prompt() -> str:
    return (_SKILLS_DIR / "generate-resume.md").read_text(encoding="utf-8").strip()


def _strip_code_fence(text: str) -> str:
    """Remove outer ``` wrapper that many models add despite being told not to."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    lines = lines[1:]  # opening fence (``` or ```markdown)
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _clean_markdown(raw_text: str) -> str:
    """Drop fences, any preamble before the name, and stray inline markdown."""
    text = _strip_code_fence(raw_text)
    lines = text.splitlines()
    first_h1 = next((i for i, l in enumerate(lines) if l.strip().startswith("# ")), 0)
    text = "\n".join(lines[first_h1:])
    return text.replace("`", "")


# ── Job-description alignment checks ─────────────────────────────────────────

# Lower-case technical vocabulary that CamelCase/acronym detection cannot see.
_SINGLE = set(
    "python agentic rag docker kubernetes pytorch tensorflow aws azure gcp embedding embeddings "
    "quantization inference observability microservice microservices orchestration evaluation "
    "evaluations monitoring fastapi postgresql react".split()
)
_MULTI = [
    "multi-agent", "knowledge graph", "fine-tuning", "vector search", "vector database",
    "semantic search", "tool calling", "human-in-the-loop", "llm-as-judge", "prompt engineering",
    "context engineering", "hugging face", "generative ai", "open-source", "on-premise",
    "model context protocol", "edge deployment", "multi-agent systems",
]
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:[./-][A-Za-z0-9+#]+)*")


def jd_keywords(job_description: str) -> list[str]:
    """Technical terms in a JD: CamelCase, acronyms, dotted/digit names, known vocabulary."""
    found: dict[str, str] = {}
    low = job_description.lower()
    for phrase in _MULTI:
        if re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", low):
            found.setdefault(phrase, phrase)
    for tok in _TOKEN.findall(job_description):
        tail = tok[1:]
        techy = (
            any(c.isupper() for c in tail)  # LangChain, vLLM, ONNX, GGML
            or any(c.isdigit() or c in "+#." for c in tok)  # llama.cpp, Next.js
            or tok.lower() in _SINGLE
        )
        if techy and len(tok) > 1:
            found.setdefault(tok.lower(), tok)
    return list(found.values())


def _pattern(term: str) -> re.Pattern:
    parts = [re.escape(p) for p in re.split(r"[\s\-_.]+", term.lower()) if p]
    body = r"[\s\-_.]*".join(parts)
    return re.compile(r"(?<![a-z0-9])" + body + r"s?(?![a-z0-9])", re.I)


def _contains(text: str, term: str) -> bool:
    return bool(_pattern(term.rstrip("s") if term.lower().endswith("s") and len(term) > 3 else term).search(text))


def keyword_report(job_description: str, profile: str, resume_text: str) -> dict:
    """Which honestly-supported JD keywords made it in, and which unsupported ones leaked in."""
    terms = jd_keywords(job_description)
    supported = [t for t in terms if _contains(profile, t)]
    missing = [t for t in supported if not _contains(resume_text, t)]
    # Only named tools/protocols count as fabrication; generic phrases ("multi-agent") are style.
    generic = set(_MULTI) | _SINGLE
    invented = [t for t in terms if t not in supported and t.lower() not in generic and _contains(resume_text, t)]
    coverage = 1.0 if not supported else 1 - len(missing) / len(supported)
    return {"coverage": coverage, "missing": missing, "invented": invented, "supported": supported}


# ── Page-fit measurement ─────────────────────────────────────────────────────

def _soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe", "/usr/bin/soffice"):
        if Path(p).exists():
            return p
    return None


def _count_pages_libreoffice(docx_bytes: bytes) -> int | None:
    exe = _soffice()
    if not exe:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "r.docx"
            src.write_bytes(docx_bytes)
            subprocess.run(
                [exe, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)],
                capture_output=True, timeout=90, check=True,
            )
            pdf = (Path(tmp) / "r.pdf").read_bytes()
        return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf)) or None
    except Exception:  # noqa: BLE001 - measurement is best-effort
        logger.warning("LibreOffice page count failed; falling back to estimate", exc_info=True)
        return None


def _estimate_pages(docx_bytes: bytes) -> int:
    """Rough fallback: ~122 chars/line at 10pt Times over 7.62in; ~118 for bullets."""
    doc = Document(BytesIO(docx_bytes))
    height = 0.0
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        indented = p.paragraph_format.left_indent is not None
        lines = max(1, math.ceil(len(text) / (118 if indented else 122)))
        pf = p.paragraph_format
        height += lines * 12 + (pf.space_before or 0) / 12700 + (pf.space_after or 0) / 12700
    return max(1, math.ceil(height / 743))  # 10.32in usable = 743pt


def count_pages(docx_bytes: bytes) -> int:
    return _count_pages_libreoffice(docx_bytes) or _estimate_pages(docx_bytes)


def _resume_issues(markdown_text: str, docx_bytes: bytes, profile: str, jd: str) -> list[str]:
    issues = []
    pages = count_pages(docx_bytes)
    if pages > 1:
        issues.append(
            f"The resume renders on {pages} pages; it MUST fit on exactly 1 page. Cut the least "
            "JD-relevant bullets, projects and volunteer roles, and shorten long bullets."
        )
    if "[ADD METRIC" in markdown_text:
        issues.append("Remove every [ADD METRIC ...] placeholder; use only numbers from the documents or omit the figure.")
    if jd.strip():
        rep = keyword_report(jd, profile, markdown_text)
        if rep["coverage"] < COVERAGE_TARGET and rep["missing"]:
            issues.append(
                f"Keyword coverage is {rep['coverage']:.0%}, below 90%. These job-description terms ARE "
                f"supported by the candidate documents but missing from the resume: {', '.join(rep['missing'])}. "
                "Work them into the Skills lines or relevant bullets."
            )
        if rep["invented"]:
            issues.append(
                "These job-description terms appear in the resume but are NOT in the candidate documents; "
                f"remove them: {', '.join(rep['invented'])}."
            )
    return issues


# ── Pipeline ─────────────────────────────────────────────────────────────────

def _response_text(response) -> str:
    # .text handles both plain-string and list-of-blocks content shapes
    if hasattr(response, "text"):
        return str(response.text)
    if hasattr(response, "content"):
        return str(response.content)
    return str(response)


def generate_resume_docx(profile_data: str, job_description: str, llm) -> bytes:
    """Draft a resume with the LLM, render it, and repair it until it passes the checks."""
    t0 = time.monotonic()
    callbacks = get_callbacks()

    from config import get_settings
    candidate_name = get_settings(require_api_key=False).candidate_name

    messages = [
        SystemMessage(content=_load_prompt()),
        HumanMessage(content=(
            f"Generate a complete one-page ATS-optimised resume for {candidate_name}.\n\n"
            f"<candidate_documents>\n{profile_data}\n</candidate_documents>\n\n"
            f"<job_description>\n{job_description}\n</job_description>"
        )),
    ]
    config = {"callbacks": callbacks, "run_name": "resume-generation",
              "metadata": {"candidate": candidate_name, "langfuse_tags": ["resume"]}}

    best: tuple[int, bytes] | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        t_llm = time.monotonic()
        response = llm.invoke(messages, config=config)
        raw_text = _response_text(response)
        logger.info("[resume %d/%d] LLM responded — %.1fs, %d chars (model=%s)",
                    attempt, MAX_ATTEMPTS, time.monotonic() - t_llm, len(raw_text), RESUME_MODEL)

        markdown_text = _clean_markdown(raw_text)
        if not markdown_text.strip():
            if attempt < MAX_ATTEMPTS:
                logger.warning("[resume %d/%d] empty response (metadata=%s); retrying", attempt, MAX_ATTEMPTS,
                               getattr(response, "response_metadata", None))
                continue
            raise ValueError(
                "The model returned an empty response. "
                "The free model may be rate-limited — try again in a moment, or switch to a paid model."
            )

        docx_bytes = _build_docx(markdown_text)
        issues = _resume_issues(markdown_text, docx_bytes, profile_data, job_description)
        if best is None or len(issues) < best[0]:
            best = (len(issues), docx_bytes)
        if not issues:
            break
        logger.info("[resume %d/%d] %d issue(s): %s", attempt, MAX_ATTEMPTS, len(issues), " | ".join(issues))
        messages += [
            AIMessage(content=raw_text),
            HumanMessage(content=(
                "Fix these problems and output the full corrected resume in the same format "
                "(resume only, no commentary):\n- " + "\n- ".join(issues)
            )),
        ]

    logger.info("[resume] done — docx=%d bytes, remaining issues=%d, total=%.1fs",
                len(best[1]), best[0], time.monotonic() - t0)
    return best[1]


# ── Document helpers ──────────────────────────────────────────────────────────

_INLINE = re.compile(
    r"\[(?P<label>[^\]]+)\]\((?P<url>(?:https?://|mailto:)[^)\s]+)\)"
    r"|(?P<bare>https?://[^\s,;|]+)"
    r"|(?P<mail>[\w.+-]+@[\w-]+(?:\.[\w-]+)+)"
)


def _add_hyperlink(para, text: str, url: str, size: Pt) -> None:
    rid = para.part.relate_to(
        url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)
    run = para.add_run(text)
    run.font.name, run.font.size = _FONT, size
    run.font.color.rgb = _LINK
    run.font.underline = True
    link.append(run._r)
    para._p.append(link)


def _run(para, text: str, *, size: Pt, bold=False, italic=False) -> None:
    """Add text; **bold** spans are bolded, links/URLs/emails become real hyperlinks."""
    if "**" in text:
        for i, part in enumerate(text.split("**")):
            if part:
                _run(para, part, size=size, bold=bold or i % 2 == 1, italic=italic)
        return
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            _plain(para, text[pos:m.start()], size, bold, italic)
        if m.group("label"):
            _add_hyperlink(para, m.group("label"), m.group("url"), size)
        elif m.group("bare"):
            url = m.group("bare").rstrip(".)")
            _add_hyperlink(para, url, url, size)
            _plain(para, m.group("bare")[len(url):], size, bold, italic)
        else:
            _add_hyperlink(para, m.group("mail"), "mailto:" + m.group("mail"), size)
        pos = m.end()
    if pos < len(text):
        _plain(para, text[pos:], size, bold, italic)


def _plain(para, text: str, size: Pt, bold: bool, italic: bool) -> None:
    r = para.add_run(text)
    r.font.name = _FONT
    r._r.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), _FONT)
    r.font.size = size
    r.font.bold = bold
    r.font.italic = italic
    r.font.color.rgb = _BLACK


def _para(doc: Document, *, before=0, after=0, align=None, line=_LINE):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    pf.line_spacing_rule, pf.line_spacing = WD_LINE_SPACING.EXACTLY, line
    if align is not None:
        p.alignment = align
    return p


def _add_name(doc: Document, text: str) -> None:
    p = _para(doc, after=1.9, align=WD_ALIGN_PARAGRAPH.CENTER, line=Pt(18))
    _run(p, text.strip(), size=Pt(16), bold=True)


def _add_contact(doc: Document, text: str) -> None:
    p = _para(doc, after=3.9, align=WD_ALIGN_PARAGRAPH.CENTER, line=Pt(11))
    _run(p, text.strip(), size=Pt(9))


def _add_section_heading(doc: Document, text: str) -> None:
    p = _para(doc, before=6, after=2.9, line=Pt(13))
    _run(p, text.strip().upper(), size=Pt(11), bold=True)
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", "000000")):
        bottom.set(qn(f"w:{k}"), v)
    pBdr.append(bottom)
    p._p.get_or_add_pPr().append(pBdr)


def _add_row(doc: Document, text: str, *, bold: bool, italic: bool = False,
             experience: bool = False, right_italic: bool = False) -> None:
    """`left | right` → left text with the right part flush to the right margin."""
    left, sep, right = text.strip().rpartition(" | ")
    if not sep:
        left, right = right, ""
    p = _para(doc, before=1.5 if bold else 0)
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.tab_stops.add_tab_stop(_TEXT_WIDTH, WD_TAB_ALIGNMENT.RIGHT)
    company, dash, rest = left.partition(" - ")
    if experience and dash and "|" not in left:
        # Template style: italic company, bold title, italic city.
        title, comma, city = rest.partition(", ")
        _run(p, company + " - ", size=Pt(10), bold=True, italic=True)
        _run(p, title + comma, size=Pt(10), bold=True)
        _run(p, city, size=Pt(10), bold=True, italic=True)
        _run(p, "\t" + right, size=Pt(10))
        return
    _run(p, left, size=Pt(10), bold=bold, italic=italic)
    if right:
        # University rows carry an italic location; degree rows keep a plain date.
        _run(p, "\t" + right, size=Pt(10), italic=right_italic)


def _add_bullet(doc: Document, text: str, dated: bool = False) -> None:
    p = _para(doc)
    pf = p.paragraph_format
    pf.left_indent, pf.first_line_indent = _BULLET_INDENT, -_BULLET_HANG
    pf.tab_stops.add_tab_stop(_BULLET_INDENT)
    left, sep, right = text.strip().rpartition(" | ")
    if dated and sep:  # Awards: date flush right
        pf.tab_stops.add_tab_stop(_TEXT_WIDTH, WD_TAB_ALIGNMENT.RIGHT)
        _run(p, "•\t" + left + "\t" + right, size=Pt(10))
    else:
        _run(p, "•\t" + text.strip(), size=Pt(10))


def _add_body(doc: Document, text: str) -> None:
    """Body line; a leading `Label:` is bolded (Skills lines)."""
    p = _para(doc)
    label, sep, rest = text.strip().partition(":")
    if sep and 0 < len(label) <= 40 and "http" not in label:
        _run(p, label + ":", size=Pt(10), bold=True)
        _run(p, rest, size=Pt(10))
    else:
        _run(p, text.strip(), size=Pt(10))


def _configure_document(doc: Document) -> None:
    for section in doc.sections:
        section.page_width, section.page_height = Inches(8.5), Inches(11)
        section.top_margin = section.bottom_margin = _MARGIN_TB
        section.left_margin = section.right_margin = _MARGIN_LR
    normal = doc.styles["Normal"]
    normal.font.name = _FONT
    normal.font.size = Pt(10)


# ── Core parser ───────────────────────────────────────────────────────────────

def _build_docx(markdown_text: str) -> bytes:
    """Pure function: structured Markdown resume → .docx bytes.

    The format contract is defined in skills/generate-resume.md; this function
    is the corresponding decoder.
    """
    doc = Document()
    _configure_document(doc)

    # Remove the default blank paragraph python-docx may start with.
    if doc.paragraphs and not doc.paragraphs[0].text.strip():
        p = doc.paragraphs[0]
        p._element.getparent().remove(p._element)

    found_name = False
    expect_contact = False  # True immediately after the H1 name line
    in_skills = False
    section = ""

    # Models sometimes drop the "# " on the name; treat a plain first line as the name.
    first = next((l.strip() for l in markdown_text.splitlines() if l.strip()), "")
    if first and not first.startswith("#") and "|" not in first and "@" not in first and len(first) < 60:
        markdown_text = markdown_text.replace(first, "# " + first, 1)

    for line in markdown_text.splitlines():
        stripped = line.strip()

        if not stripped:
            expect_contact = False
            continue

        if stripped.startswith("# ") and not found_name:
            _add_name(doc, stripped[2:])
            found_name = True
            expect_contact = True
            continue

        if expect_contact and not stripped.startswith("#"):
            _add_contact(doc, stripped)
            expect_contact = False
            continue

        expect_contact = False

        if stripped.startswith("## "):
            section = stripped.lower()
            in_skills = "skill" in section
            _add_section_heading(doc, stripped[3:])
        elif stripped.startswith("#### "):
            _add_row(doc, stripped[5:], bold=False, italic=True)
        elif stripped.startswith("### "):
            _add_row(doc, stripped[4:], bold=True, right_italic="education" in section,
                     experience="experience" in section and "volunteer" not in section)
        elif stripped.startswith(("- ", "* ")):
            if in_skills:
                _add_body(doc, stripped[2:])
            else:
                _add_bullet(doc, stripped[2:], dated="award" in section)
        else:
            _add_body(doc, stripped)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
