"""Skill files, registry, and the 6500-token cap."""

import pytest

import config
from config import get_settings
from graph import build_llm
from skills import ACTIONS, DRAFTING_SKILLS, SKILLS, load_skill


def test_there_are_exactly_four_skill_buttons():
    assert list(ACTIONS) == ["review", "ats", "cover_letter", "email"]


@pytest.mark.parametrize("key", list(SKILLS))
def test_every_skill_file_exists_and_has_content(key):
    assert len(load_skill(key)) > 500


@pytest.mark.parametrize("key", list(SKILLS))
def test_every_button_has_a_label_and_instruction(key):
    label, instruction = ACTIONS[key]
    assert label.strip()
    assert "job description" in instruction.lower()


def test_drafting_skills_are_real_skills():
    assert DRAFTING_SKILLS <= set(SKILLS)


def test_the_ats_skill_leaves_scoring_to_python():
    text = load_skill("ats")
    assert "NOT yours to compute" in text
    assert "Output a bolded ATS Match Score" not in text


@pytest.mark.parametrize("key", ["review", "cover_letter", "email"])
def test_skills_that_need_a_job_description_are_told_where_it_is(key):
    assert "<job_description>" in load_skill(key)


def test_cover_letter_skill_requires_a_conventional_letter_only():
    text = load_skill("cover_letter")
    assert "standard letter" in text
    assert "Return only the finished cover letter" in text
    assert "Do not use section headings" in text
    assert "bullet points" in text


def test_skill_responses_are_capped_at_6500_tokens():
    assert get_settings().skill_max_tokens == 6500 == config.DEFAULT_SKILL_MAX_TOKENS


def test_build_llm_can_override_the_response_cap():
    assert build_llm(max_tokens=6500).max_tokens == 6500
    assert build_llm().max_tokens == get_settings().max_tokens
