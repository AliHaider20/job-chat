"""Drafting uses a higher temperature than analysis."""

import pytest

import config
from config import get_settings
from graph import build_llm
from skills import DRAFTING_SKILLS


def test_drafting_is_warmer_than_analysis():
    settings = get_settings()
    assert settings.drafting_temperature > settings.temperature


def test_only_the_writing_skills_draft():
    assert DRAFTING_SKILLS == {"cover_letter", "email"}


def test_default_temperatures():
    assert config.DEFAULT_TEMPERATURE == 0.0
    assert 0 < config.DEFAULT_DRAFTING_TEMPERATURE < 1


def test_build_llm_defaults_to_the_analysis_temperature():
    assert build_llm().temperature == pytest.approx(get_settings().temperature, abs=1e-6)
    assert build_llm().openai_api_base == config.OPENROUTER_BASE_URL


def test_build_llm_accepts_an_override():
    assert build_llm(0.4).temperature == 0.4


def test_drafting_temperature_is_configurable(monkeypatch):
    monkeypatch.setenv("LLM_DRAFTING_TEMPERATURE", "0.9")
    get_settings.cache_clear()
    try:
        assert get_settings().drafting_temperature == 0.9
    finally:
        get_settings.cache_clear()
