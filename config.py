"""Application configuration, loaded once from the environment."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent

DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 2048
DEFAULT_DATA_DIR = "data"
DEFAULT_LANGFUSE_HOST = "https://cloud.langfuse.com"
DEFAULT_CHECKPOINT_DB = "checkpoints.sqlite"


class ConfigError(RuntimeError):
    """Raised when the environment is missing or misconfigured."""


@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    candidate_name: str
    data_dir: Path
    model: str
    temperature: float
    max_tokens: int
    checkpoint_db: Path
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_host: str

    @property
    def tracing_enabled(self) -> bool:
        """Tracing turns itself on only when both Langfuse keys are present."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


def _get_float(name, default):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}")


def _get_int(name, default):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}")


def _resolve_data_dir():
    raw = os.getenv("DATA_DIR", "").strip() or DEFAULT_DATA_DIR
    data_dir = Path(raw)
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir

    if not data_dir.is_dir():
        raise ConfigError(
            f"DATA_DIR does not exist: {data_dir}\n"
            f"Set DATA_DIR in .env to the folder holding your profile documents, "
            f"or remove it to use the default ({PROJECT_ROOT / DEFAULT_DATA_DIR})."
        )
    if not any(data_dir.glob("*.md")):
        raise ConfigError(
            f"No .md documents found in {data_dir}\n"
            f"Run pdf_2_markdown_converter.py to convert your PDFs first."
        )
    return data_dir


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("GROQ_API_KEY is not set. Add it to your .env file.")

    return Settings(
        groq_api_key=api_key,
        candidate_name=os.getenv("CANDIDATE_NAME", "").strip() or "the candidate",
        data_dir=_resolve_data_dir(),
        model=os.getenv("GROQ_MODEL", "").strip() or DEFAULT_MODEL,
        temperature=_get_float("LLM_TEMPERATURE", DEFAULT_TEMPERATURE),
        max_tokens=_get_int("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS),
        checkpoint_db=PROJECT_ROOT / (
            os.getenv("CHECKPOINT_DB", "").strip() or DEFAULT_CHECKPOINT_DB
        ),
        langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "").strip(),
        langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY", "").strip(),
        # LANGFUSE_HOST is the SDK's own name; LANGFUSE_BASE_URL is accepted as an alias.
        langfuse_host=(
            os.getenv("LANGFUSE_HOST", "").strip()
            or os.getenv("LANGFUSE_BASE_URL", "").strip()
            or DEFAULT_LANGFUSE_HOST
        ),
    )
