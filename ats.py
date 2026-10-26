"""ATS keyword analysis.

The model classifies keywords; Python computes the score. Counting and
arithmetic are exactly what language models are unreliable at, so the score is
derived from the length of the returned lists and cannot disagree with them.
"""

from pydantic import BaseModel, Field


class MatchedKeyword(BaseModel):
    keyword: str = Field(description="The keyword exactly as written in the job description.")
    evidence: str = Field(description="Where it appears in the candidate documents: project, role, or skill list.")


class MissingKeyword(BaseModel):
    keyword: str = Field(description="The keyword exactly as written in the job description.")
    closest: str = Field(description="The nearest thing the candidate does have, or 'no adjacent experience'.")


class PriorityFix(BaseModel):
    keyword: str = Field(description="A missing keyword worth addressing.")
    can_honestly_add: bool = Field(
        description="True if evidence already exists in the documents and only needs surfacing. "
                    "False if the candidate would have to genuinely acquire the skill."
    )
    note: str = Field(description="One sentence on what to do about it.")


class BulletRewrite(BaseModel):
    original: str = Field(description="An existing resume bullet, copied from the candidate documents.")
    rewritten: str = Field(
        description="The bullet reworded to name a missing keyword the candidate can honestly claim. "
                    "Use a bracketed placeholder such as [ADD METRIC] instead of inventing numbers."
    )


class ATSAnalysis(BaseModel):
    """Keyword classification of a job description against the candidate documents."""

    matched: list[MatchedKeyword] = Field(
        description="Every job-description keyword the candidate documents support."
    )
    missing: list[MissingKeyword] = Field(
        description="Every job-description keyword the candidate documents do not support."
    )
    priority_fixes: list[PriorityFix] = Field(
        description="Up to three missing keywords that would most improve the score, most valuable first."
    )
    rewrites: list[BulletRewrite] = Field(
        default_factory=list,
        description="Two or three existing resume bullets rewritten to surface the highest-priority "
                    "honestly addable keywords. Empty if none can be added truthfully."
    )


def format_ats_report(analysis: ATSAnalysis) -> str:
    """Render the analysis, computing the score from the list lengths."""
    matched, missing = analysis.matched, analysis.missing
    total = len(matched) + len(missing)
    if total == 0:
        return "No keywords could be extracted from the job description. Check that one is loaded."

    score = round(100 * len(matched) / total)

    lines = [
        f"## ATS score: {score}%",
        "",
        f"**{len(matched)} of {total}** job-description keywords are supported by your documents.",
        "",
        f"## Matched keywords ({len(matched)})",
        "",
    ]
    lines += [f"{i}. **{k.keyword}** — {k.evidence}" for i, k in enumerate(matched, 1)] or ["_None._"]

    lines += ["", f"## Missing keywords ({len(missing)})", ""]
    lines += [f"{i}. **{k.keyword}** — {k.closest}" for i, k in enumerate(missing, 1)] or ["_None._"]

    if analysis.priority_fixes:
        lines += ["", "## Priority fixes", ""]
        for i, fix in enumerate(analysis.priority_fixes, 1):
            tag = "can surface honestly" if fix.can_honestly_add else "requires actually learning it"
            lines.append(f"{i}. **{fix.keyword}** _({tag})_ — {fix.note}")

    if analysis.rewrites:
        lines += ["", "## Suggested rewrites", ""]
        for i, rewrite in enumerate(analysis.rewrites, 1):
            lines += [f"{i}. **Before:** {rewrite.original}", f"   **After:** {rewrite.rewritten}"]

    return "\n".join(lines)
