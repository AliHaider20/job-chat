import pytest

import config
from config import ConfigError, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / "resume.md").write_text("# Resume", encoding="utf-8")
    return tmp_path


@pytest.fixture
def base_env(monkeypatch, data_dir):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    for name in ("OPENROUTER_MODEL", "LLM_TEMPERATURE", "LLM_MAX_TOKENS", "MAX_HISTORY_TURNS",
                 "CANDIDATE_NAME", "LANGFUSE_HOST", "LANGFUSE_BASE_URL",
                 "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_missing_api_key_is_rejected(base_env, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "   ")
    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        get_settings()


def test_nonexistent_data_dir_is_rejected(base_env, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "nope"))
    with pytest.raises(ConfigError, match="DATA_DIR does not exist"):
        get_settings()


def test_data_dir_without_markdown_is_rejected(base_env, monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("DATA_DIR", str(empty))
    with pytest.raises(ConfigError, match="No .md documents"):
        get_settings()


@pytest.mark.parametrize("var", ["LLM_TEMPERATURE", "LLM_MAX_TOKENS", "MAX_HISTORY_TURNS"])
def test_non_numeric_values_are_rejected(base_env, monkeypatch, var):
    monkeypatch.setenv(var, "hot")
    with pytest.raises(ConfigError, match=var):
        get_settings()


def test_defaults_apply_when_optional_vars_are_unset(base_env):
    settings = get_settings()
    assert settings.openrouter_api_key == "test-key"
    assert settings.model == config.DEFAULT_MODEL
    assert settings.temperature == config.DEFAULT_TEMPERATURE
    assert settings.max_tokens == config.DEFAULT_MAX_TOKENS
    assert settings.max_history_turns == config.DEFAULT_MAX_HISTORY_TURNS
    assert settings.candidate_name == "the candidate"


def test_overrides_are_read_from_the_environment(base_env, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "some/other-model")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
    monkeypatch.setenv("MAX_HISTORY_TURNS", "3")
    settings = get_settings()
    assert settings.model == "some/other-model"
    assert settings.temperature == 0.7
    assert settings.max_history_turns == 3


def test_relative_data_dir_resolves_against_the_project_root(base_env, monkeypatch, tmp_path):
    """A relative DATA_DIR must not depend on the process working directory."""
    project_root = tmp_path / "project"
    (project_root / "docs").mkdir(parents=True)
    (project_root / "docs" / "resume.md").write_text("# Resume", encoding="utf-8")

    monkeypatch.setattr(config, "PROJECT_ROOT", project_root)
    monkeypatch.setenv("DATA_DIR", "docs")

    assert get_settings().data_dir == project_root / "docs"


class TestLangfuseHost:
    """LANGFUSE_BASE_URL is an alias; getting this wrong silently traced to the wrong region."""

    def test_defaults_when_neither_is_set(self, base_env):
        assert get_settings().langfuse_host == config.DEFAULT_LANGFUSE_HOST

    def test_base_url_alias_is_honoured(self, base_env, monkeypatch):
        monkeypatch.setenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")
        assert get_settings().langfuse_host == "https://us.cloud.langfuse.com"

    def test_host_wins_over_the_alias(self, base_env, monkeypatch):
        monkeypatch.setenv("LANGFUSE_HOST", "https://host.example")
        monkeypatch.setenv("LANGFUSE_BASE_URL", "https://alias.example")
        assert get_settings().langfuse_host == "https://host.example"


class TestTracingEnabled:
    def test_off_without_keys(self, base_env):
        assert get_settings().tracing_enabled is False

    def test_off_with_only_one_key(self, base_env, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        assert get_settings().tracing_enabled is False

    def test_on_with_both_keys(self, base_env, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        assert get_settings().tracing_enabled is True
