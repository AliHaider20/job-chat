"""The ATS score is computed in Python, so it is fully testable without an API."""

import re

import pytest

from ats import ATSAnalysis, MatchedKeyword, MissingKeyword, PriorityFix, format_ats_report


def analysis(matched=0, missing=0, fixes=()):
    return ATSAnalysis(
        matched=[MatchedKeyword(keyword=f"K{i}", evidence=f"project {i}") for i in range(matched)],
        missing=[MissingKeyword(keyword=f"M{i}", closest="no adjacent experience") for i in range(missing)],
        priority_fixes=list(fixes),
    )


def score_of(report):
    return int(re.search(r"ATS score: (\d+)%", report).group(1))


@pytest.mark.parametrize(
    "matched,missing,expected",
    [(15, 8, 65), (10, 0, 100), (0, 10, 0), (1, 2, 33), (2, 1, 67), (7, 7, 50), (1, 1, 50)],
)
def test_score_is_matched_over_total(matched, missing, expected):
    assert score_of(format_ats_report(analysis(matched, missing))) == expected


@pytest.mark.parametrize("matched,missing", [(15, 8), (3, 9), (0, 4), (6, 0)])
def test_score_always_agrees_with_the_rendered_lists(matched, missing):
    """The regression this design exists to prevent: score disagreeing with its own lists."""
    report = format_ats_report(analysis(matched, missing))
    listed_matched = len(re.findall(r"^\d+\. \*\*K", report, re.M))
    listed_missing = len(re.findall(r"^\d+\. \*\*M", report, re.M))
    total = listed_matched + listed_missing

    assert listed_matched == matched
    assert listed_missing == missing
    assert score_of(report) == round(100 * listed_matched / total)


def test_empty_analysis_does_not_divide_by_zero():
    report = format_ats_report(analysis(0, 0))
    assert "No keywords" in report
    assert "%" not in report


def test_counts_appear_in_headings_and_summary():
    report = format_ats_report(analysis(4, 6))
    assert "## Matched keywords (4)" in report
    assert "## Missing keywords (6)" in report
    assert "**4 of 10**" in report


def test_priority_fixes_distinguish_honest_from_must_learn():
    fixes = [
        PriorityFix(keyword="SQL", can_honestly_add=True, note="surface it"),
        PriorityFix(keyword="Rust", can_honestly_add=False, note="learn it"),
    ]
    report = format_ats_report(analysis(1, 1, fixes))
    assert "can surface honestly" in report
    assert "requires actually learning it" in report


def test_priority_section_omitted_when_there_are_no_fixes():
    assert "## Priority fixes" not in format_ats_report(analysis(2, 2))


def test_rewrites_are_rendered_before_and_after():
    from ats import BulletRewrite

    result = analysis(1, 1)
    result.rewrites = [BulletRewrite(original="Built a pipeline", rewritten="Built a Kafka pipeline")]
    report = format_ats_report(result)
    assert "## Suggested rewrites" in report
    assert "**Before:** Built a pipeline" in report
    assert "**After:** Built a Kafka pipeline" in report


def test_rewrites_section_omitted_when_there_are_none():
    assert "## Suggested rewrites" not in format_ats_report(analysis(2, 2))
