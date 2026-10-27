"""The suite must not touch the developer's real credentials or documents.

Without this, load_dotenv() silently pulls the real .env into every test run,
which sent traces to the live Langfuse project.
"""

from config import get_settings


def test_real_langfuse_credentials_are_not_loaded():
    settings = get_settings()
    assert settings.langfuse_public_key == ""
    assert settings.langfuse_secret_key == ""


def test_tracing_is_disabled_during_tests():
    assert get_settings().tracing_enabled is False


def test_the_real_openrouter_key_is_not_used():
    assert get_settings().openrouter_api_key == "test-key-not-used"


def test_profile_documents_are_not_loaded_during_startup():
    assert not hasattr(get_settings(), "data_dir")
