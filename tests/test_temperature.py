"""Drafting uses a higher temperature than analysis."""

import pytest

import config
from config import get_settings
from graph import DRAFTING_ACTIONS, build_llm


def test_drafting_is_warmer_than_analysis():
    settings = get_settings()
    assert settings.drafting_temperature > settings.temperature


def test_only_the_cover_letter_drafts():
    assert DRAFTING_ACTIONS == {"cover_letter"}


def test_default_temperatures():
    assert config.DEFAULT_TEMPERATURE == 0.0
    assert 0 < config.DEFAULT_DRAFTING_TEMPERATURE < 1


def test_build_llm_defaults_to_the_analysis_temperature():
    # ChatGroq clamps an exact 0.0 to 1e-08, since Groq rejects zero.
    assert build_llm().temperature == pytest.approx(get_settings().temperature, abs=1e-6)


def test_build_llm_accepts_an_override():
    assert build_llm(0.4).temperature == 0.4


def test_drafting_temperature_is_configurable(monkeypatch):
    monkeypatch.setenv("LLM_DRAFTING_TEMPERATURE", "0.9")
    get_settings.cache_clear()
    try:
        assert get_settings().drafting_temperature == 0.9
    finally:
        get_settings.cache_clear()
