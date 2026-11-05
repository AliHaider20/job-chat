"""Rigorous tests for resume.py — ATS format rules, document structure, pipeline."""

from io import BytesIO
from unittest.mock import MagicMock

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from resume import _build_docx, _strip_code_fence, generate_resume_docx

# ── Fixtures ──────────────────────────────────────────────────────────────────

FULL_MARKDOWN = """\
# Jane Smith
jane@example.com | +1 555-000-0000 | New York, NY | linkedin.com/in/jane

## Summary
Experienced software engineer with 5 years building scalable distributed systems.

## Skills
- Languages: Python, Go, TypeScript
- Infrastructure: AWS, Docker, Kubernetes, PostgreSQL

## Experience

### Senior Software Engineer — Acme Corp | Jan 2022 – Present
- Led migration of monolith to microservices, reducing p99 latency by 40%
- Built CI/CD pipeline with GitHub Actions serving 50 engineers

### Software Engineer — Beta Inc | Jun 2019 – Dec 2021
- Developed REST APIs handling 1M daily requests
- Mentored 3 junior engineers through onboarding

## Education

### B.S. Computer Science — State University | 2019
- Dean's List, GPA 3.9

## Projects

### OpenMetrics Dashboard | 2021
- Built real-time Prometheus dashboard with Grafana used by 200+ engineers

## Certifications
- AWS Certified Developer — Amazon | 2022
""".strip()

MINIMAL_MARKDOWN = "# John Doe\njohn@example.com"

SKILLS_ONLY_MARKDOWN = """\
# Pat Jones
pat@example.com | 555-111-2222

## Skills
- Tools: Git, Linux, Bash
""".strip()


@pytest.fixture(autouse=True)
def _no_libreoffice(monkeypatch):
    """Keep unit tests fast: use the estimator; a dedicated test exercises LibreOffice."""
    monkeypatch.setattr("resume._count_pages_libreoffice", lambda _b: None)


def _doc(raw: bytes) -> Document:
    return Document(BytesIO(raw))


# ── Basic output ──────────────────────────────────────────────────────────────

def test_returns_bytes():
    assert isinstance(_build_docx(FULL_MARKDOWN), bytes)


def test_non_empty_output():
    assert len(_build_docx(FULL_MARKDOWN)) > 1000


def test_empty_markdown_does_not_crash():
    result = _build_docx("")
    _doc(result)  # must not raise


def test_minimal_markdown_does_not_crash():
    result = _build_docx(MINIMAL_MARKDOWN)
    doc = _doc(result)
    assert any("John Doe" in p.text for p in doc.paragraphs)


# ── ATS hard rules ────────────────────────────────────────────────────────────

def test_no_tables():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    assert len(doc.tables) == 0, "ATS rule: tables are forbidden"


def test_no_text_in_header():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    for section in doc.sections:
        header_text = " ".join(p.text for p in section.header.paragraphs).strip()
        assert not header_text, "Name/contact must be in the body, not the Word header"


def test_no_text_in_footer():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    for section in doc.sections:
        footer_text = " ".join(p.text for p in section.footer.paragraphs).strip()
        assert not footer_text, "Content must be in the body, not the Word footer"


def test_no_inline_images():
    # Inline images appear as <a:blip> elements; a proper text-only resume has none.
    from lxml import etree
    doc = _doc(_build_docx(FULL_MARKDOWN))
    xml = etree.tostring(doc.element)
    assert b"a:blip" not in xml, "ATS rule: no images allowed"


def test_font_is_template_font():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    for para in doc.paragraphs:
        for run in para.runs:
            if run.text.strip():
                assert run.font.name in ("Times New Roman", None), (
                    f"Unexpected font {run.font.name!r} in: {run.text[:40]!r}"
                )


def test_body_font_size_in_range():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    for para in doc.paragraphs:
        for run in para.runs:
            if run.font.size and run.text.strip():
                assert Pt(9) <= run.font.size <= Pt(20), (
                    f"Font size {run.font.size / 12700:.1f}pt out of range in: {run.text[:40]!r}"
                )


# ── Name and contact ──────────────────────────────────────────────────────────

def test_name_is_first_paragraph():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    first = doc.paragraphs[0]
    assert "Jane Smith" in first.text


def test_name_paragraph_is_centered():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    assert doc.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER


def test_name_font_size_at_least_16pt():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    name_para = doc.paragraphs[0]
    assert any(
        r.font.size and r.font.size >= Pt(16)
        for r in name_para.runs
    ), "Name must be at least 16pt"


def test_name_is_bold():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    assert any(r.font.bold for r in doc.paragraphs[0].runs)


def test_contact_line_is_second_paragraph():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    second = doc.paragraphs[1]
    assert "jane@example.com" in second.text


def test_contact_paragraph_is_centered():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    assert doc.paragraphs[1].alignment == WD_ALIGN_PARAGRAPH.CENTER


def test_contact_font_size_is_small():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    contact_para = doc.paragraphs[1]
    for run in contact_para.runs:
        if run.font.size:
            assert run.font.size <= Pt(11), "Contact line should be compact (≤ 11pt)"


# ── Section headings ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("section", ["SUMMARY", "SKILLS", "EXPERIENCE", "EDUCATION"])
def test_required_section_headings_present(section):
    doc = _doc(_build_docx(FULL_MARKDOWN))
    texts = [p.text.upper() for p in doc.paragraphs]
    assert any(section in t for t in texts), f"Section '{section}' not found"


def test_optional_sections_present_when_in_markdown():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    texts = [p.text.upper() for p in doc.paragraphs]
    assert any("PROJECTS" in t for t in texts)
    assert any("CERTIFICATIONS" in t for t in texts)


def test_section_headings_are_bold():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    for para in doc.paragraphs:
        if para.text.strip().upper() in ("SUMMARY", "SKILLS", "EXPERIENCE", "EDUCATION"):
            assert any(r.font.bold for r in para.runs), f"Section heading '{para.text}' must be bold"


def test_section_heading_font_size():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    for para in doc.paragraphs:
        if para.text.strip().upper() in ("SUMMARY", "SKILLS", "EXPERIENCE", "EDUCATION"):
            for run in para.runs:
                if run.font.size:
                    assert run.font.size >= Pt(11), "Section headings should be ≥ 11pt"


# ── Subsections and bullets ───────────────────────────────────────────────────

def test_job_titles_present():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    texts = [p.text for p in doc.paragraphs]
    assert any("Acme Corp" in t for t in texts)
    assert any("Beta Inc" in t for t in texts)


def test_subsections_are_bold():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    for para in doc.paragraphs:
        if "Acme Corp" in para.text or "Beta Inc" in para.text:
            assert any(r.font.bold for r in para.runs), f"Subsection '{para.text}' must be bold"


def test_bullets_start_with_unicode_bullet():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    bullet_paras = [p for p in doc.paragraphs if p.text.startswith("•")]
    assert len(bullet_paras) >= 4, f"Expected ≥ 4 bullets, got {len(bullet_paras)}"


def test_bullet_font_size():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    for para in doc.paragraphs:
        if para.text.startswith("•"):
            for run in para.runs:
                if run.font.size:
                    assert Pt(9) <= run.font.size <= Pt(12), (
                        f"Bullet font size {run.font.size / 12700:.1f}pt out of range"
                    )


def test_bullets_have_left_indent():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    for para in doc.paragraphs:
        if para.text.startswith("•"):
            assert para.paragraph_format.left_indent is not None
            assert para.paragraph_format.left_indent > 0


# ── Margins ───────────────────────────────────────────────────────────────────

def test_page_margins_match_template():
    from docx.shared import Inches
    doc = _doc(_build_docx(FULL_MARKDOWN))
    for section in doc.sections:
        assert abs(section.top_margin - Inches(0.34)) < 5000
        assert abs(section.left_margin - Inches(0.44)) < 5000


# ── Paragraph ordering ────────────────────────────────────────────────────────

def test_section_order_summary_before_experience():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    texts = [p.text.upper() for p in doc.paragraphs]
    summary_idx = next((i for i, t in enumerate(texts) if "SUMMARY" in t), None)
    experience_idx = next((i for i, t in enumerate(texts) if "EXPERIENCE" in t), None)
    assert summary_idx is not None and experience_idx is not None
    assert summary_idx < experience_idx, "Summary must appear before Experience"


def test_section_order_experience_before_education():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    texts = [p.text.upper() for p in doc.paragraphs]
    experience_idx = next((i for i, t in enumerate(texts) if "EXPERIENCE" in t), None)
    education_idx = next((i for i, t in enumerate(texts) if "EDUCATION" in t), None)
    assert experience_idx is not None and education_idx is not None
    assert experience_idx < education_idx, "Experience must appear before Education"


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_skills_only_does_not_crash():
    doc = _doc(_build_docx(SKILLS_ONLY_MARKDOWN))
    texts = [p.text for p in doc.paragraphs]
    assert any("Pat Jones" in t for t in texts)
    assert any("Skills" in t.title() for t in texts)


def test_extra_blank_lines_do_not_create_empty_paragraphs_at_start():
    md = "\n\n\n" + FULL_MARKDOWN
    doc = _doc(_build_docx(md))
    assert doc.paragraphs[0].text.strip(), "First paragraph should not be blank"


def test_stray_h1_after_name_is_rendered_as_body():
    md = "# Jane Doe\njane@example.com\n# Stray Heading\n## Summary\nText."
    doc = _doc(_build_docx(md))
    texts = [p.text for p in doc.paragraphs]
    assert any("Stray Heading" in t for t in texts)


# ── LLM pipeline (mocked) ────────────────────────────────────────────────────

def _mock_llm(text: str) -> MagicMock:
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.text = text
    mock_llm.invoke.return_value = mock_response
    return mock_llm


def test_generate_resume_docx_calls_llm_with_both_inputs():
    mock_llm = _mock_llm(FULL_MARKDOWN)

    result = generate_resume_docx("my profile text", "job description text", mock_llm)

    assert isinstance(result, bytes)
    mock_llm.invoke.assert_called_once()
    call_args = mock_llm.invoke.call_args[0][0]  # list of messages
    assert any("resume" in str(m.content).lower() for m in call_args)
    human_content = call_args[-1].content
    assert "my profile text" in human_content
    assert "job description text" in human_content


def test_generate_resume_docx_returns_valid_docx():
    raw = generate_resume_docx("profile", "jd", _mock_llm(FULL_MARKDOWN))
    doc = _doc(raw)
    assert any("Jane Smith" in p.text for p in doc.paragraphs)


def test_generate_resume_docx_handles_response_without_text_or_content():
    """Object with neither .text nor .content — falls back to str()."""
    class _Resp:
        def __str__(self):
            return MINIMAL_MARKDOWN

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = _Resp()

    result = generate_resume_docx("profile", "jd", mock_llm)
    assert isinstance(result, bytes)


# ── Code-fence stripping ─────────────────────────────────────────────────────

def test_strip_code_fence_plain():
    assert _strip_code_fence("# Jane\njane@x.com") == "# Jane\njane@x.com"


def test_strip_code_fence_removes_backtick_wrapper():
    fenced = "```\n# Jane\njane@x.com\n```"
    assert _strip_code_fence(fenced) == "# Jane\njane@x.com"


def test_strip_code_fence_removes_language_tag():
    fenced = "```markdown\n# Jane\njane@x.com\n```"
    assert _strip_code_fence(fenced) == "# Jane\njane@x.com"


def test_strip_code_fence_no_closing_fence():
    fenced = "```\n# Jane\njane@x.com"
    assert _strip_code_fence(fenced) == "# Jane\njane@x.com"


def test_strip_code_fence_with_preamble_is_unchanged():
    # Preamble outside fence is NOT stripped — caller should not pass mixed text
    text = "Here's your resume:\n\n```\n# Jane\n```"
    assert "Here's your resume:" in _strip_code_fence(text)


def test_build_docx_with_fenced_input():
    fenced = "```\n" + FULL_MARKDOWN + "\n```"
    doc = _doc(_build_docx(_strip_code_fence(fenced)))
    assert any("Jane Smith" in p.text for p in doc.paragraphs)


# ── Empty LLM response guard ──────────────────────────────────────────────────

def test_generate_resume_docx_raises_on_empty_llm_response():
    with pytest.raises(ValueError, match="empty response"):
        generate_resume_docx("profile", "jd", _mock_llm(""))


def test_generate_resume_docx_raises_on_whitespace_only_response():
    with pytest.raises(ValueError, match="empty response"):
        generate_resume_docx("profile", "jd", _mock_llm("   \n\n   "))


# ── Skill file ────────────────────────────────────────────────────────────────

def test_resume_skill_file_exists_and_has_content():
    from config import PROJECT_ROOT
    path = PROJECT_ROOT / "skills" / "generate-resume.md"
    assert path.exists(), "skills/generate-resume.md must exist"
    assert len(path.read_text(encoding="utf-8").strip()) > 500


def test_resume_skill_file_forbids_invented_facts():
    from config import PROJECT_ROOT
    text = (PROJECT_ROOT / "skills" / "generate-resume.md").read_text(encoding="utf-8")
    assert "Never invent" in text or "never invent" in text


def test_resume_skill_file_bans_metric_placeholders():
    from config import PROJECT_ROOT
    text = (PROJECT_ROOT / "skills" / "generate-resume.md").read_text(encoding="utf-8")
    assert "No placeholders" in text


def test_resume_skill_file_forbids_markdown_tables():
    from config import PROJECT_ROOT
    text = (PROJECT_ROOT / "skills" / "generate-resume.md").read_text(encoding="utf-8")
    assert "table" in text.lower()


def test_resume_skill_file_requires_keyword_coverage():
    from config import PROJECT_ROOT
    text = (PROJECT_ROOT / "skills" / "generate-resume.md").read_text(encoding="utf-8")
    assert "90%" in text, "Prompt must instruct 90% keyword coverage"


def test_resume_skill_file_has_line_length_guidance():
    from config import PROJECT_ROOT
    text = (PROJECT_ROOT / "skills" / "generate-resume.md").read_text(encoding="utf-8")
    assert "115" in text or "120" in text, "Prompt must specify max chars per line"


# ── Template layout ───────────────────────────────────────────────────────────

def test_row_date_is_right_aligned_via_tab():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    row = next(p for p in doc.paragraphs if "Acme Corp" in p.text)
    assert "\t" in row.text and row.text.endswith("Present")
    assert row.paragraph_format.tab_stops[0].alignment is not None


def test_skills_lines_have_no_bullet_and_bold_label():
    doc = _doc(_build_docx(FULL_MARKDOWN))
    line = next(p for p in doc.paragraphs if p.text.startswith("Languages:"))
    assert line.runs[0].font.bold and not line.runs[1].font.bold


def test_markdown_links_become_hyperlinks():
    md = "\n".join(["# A B", "[LinkedIn](https://linkedin.com/in/x) | a@b.com", "## Skills", "- X: y"])
    doc = _doc(_build_docx(md))
    assert len(doc.paragraphs[1]._p.findall(".//" + "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hyperlink")) == 2
    assert "LinkedIn" in doc.paragraphs[1].text


# ── JD alignment checks ───────────────────────────────────────────────────────

def test_keyword_report_flags_missing_and_invented():
    from resume import keyword_report
    jd = "Need LangChain, Neo4j, Docker and RAG experience."
    profile = "Built RAG with LangChain and Docker."
    rep = keyword_report(jd, profile, "Used LangChain. Also Neo4j.")
    assert set(rep["missing"]) == {"Docker", "RAG"}
    assert rep["invented"] == ["Neo4j"]


def test_retry_loop_repairs_missing_keywords():
    bad = "\n".join(["# A B", "x@y.com", "## Skills", "- Tools: Git"])
    good = bad + ", LangChain"
    llm = MagicMock()
    llm.invoke.side_effect = [MagicMock(text=bad), MagicMock(text=good)]
    out = generate_resume_docx("uses LangChain", "We need LangChain.", llm)
    assert llm.invoke.call_count == 2
    assert "LangChain" in " ".join(p.text for p in _doc(out).paragraphs)


def test_plain_first_line_is_promoted_to_name():
    doc = _doc(_build_docx("Jane Doe\njane@x.com | 555\n## Skills\n- A: b"))
    assert doc.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert doc.paragraphs[0].runs[0].font.size >= Pt(16)


def test_generic_phrases_are_not_flagged_as_invented():
    from resume import keyword_report
    rep = keyword_report("Multi-agent systems, open-source models, AutoGen", "Python", "multi-agent open-source AutoGen")
    assert rep["invented"] == ["AutoGen"]


# ── ODT-parity details ────────────────────────────────────────────────────────

def _md(*lines):
    return "\n".join(lines)


def test_bold_span_in_bullet_is_bold_only_for_span():
    doc = _doc(_build_docx(_md("# A B", "x@y.com", "## Experience", "### Co - Eng, NY | 2020",
                               "- Cut cost **30%** overall")))
    bullet = next(p for p in doc.paragraphs if p.text.startswith("•"))
    assert [(r.text, bool(r.font.bold)) for r in bullet.runs if r.text.strip()] == [
        ("•\tCut cost ", False), ("30%", True), (" overall", False)]


def test_experience_row_styles_company_title_city():
    doc = _doc(_build_docx(_md("# A B", "x@y.com", "## Experience", "### Credo - ML Engineer, Austin, TX | 2020")))
    row = next(p for p in doc.paragraphs if "Credo" in p.text)
    assert row.runs[0].font.italic and not row.runs[1].font.italic and row.runs[2].font.italic


def test_award_date_flush_right():
    doc = _doc(_build_docx(_md("# A B", "x@y.com", "## Awards & Honors", "- Best paper | May 2024")))
    p = next(p for p in doc.paragraphs if "Best paper" in p.text)
    assert p.text.endswith("\tMay 2024")
