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
# Drafting a cover letter is writing, not analysis: a little sampling gives
# natural prose. Kept low so it does not start inventing detail.
DEFAULT_DRAFTING_TEMPERATURE = 0.4
# The preset actions (ATS keyword tables, detailed reviews) run long, so 2048
# truncated them mid-answer. The ceiling is Groq's free-tier limit of 8000
# tokens per minute, which counts input + max_tokens together: profile (~3.9k)
# plus job description plus this value must stay under it.
DEFAULT_MAX_TOKENS = 3000
DEFAULT_DATA_DIR = "data"
DEFAULT_LANGFUSE_HOST = "https://cloud.langfuse.com"
DEFAULT_CHECKPOINT_DB = "checkpoints.sqlite"
# Turns of conversation replayed to the model. Older turns stay in the
# checkpoint (nothing is deleted) but are not resent.
DEFAULT_MAX_HISTORY_TURNS = 10
# Routing and retrieval. ONNX runtime, so no torch dependency.
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_RETRIEVAL_TOP_K = 5


class ConfigError(RuntimeError):
    """Raised when the environment is missing or misconfigured."""


@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    candidate_name: str
    data_dir: Path
    model: str
    temperature: float
    drafting_temperature: float
    max_tokens: int
    max_history_turns: int
    embedding_model: str
    retrieval_top_k: int
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
        drafting_temperature=_get_float("LLM_DRAFTING_TEMPERATURE", DEFAULT_DRAFTING_TEMPERATURE),
        max_tokens=_get_int("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS),
        max_history_turns=_get_int("MAX_HISTORY_TURNS", DEFAULT_MAX_HISTORY_TURNS),
        embedding_model=os.getenv("EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL,
        retrieval_top_k=_get_int("RETRIEVAL_TOP_K", DEFAULT_RETRIEVAL_TOP_K),
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
