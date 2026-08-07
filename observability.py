"""Langfuse tracing.

Tracing is strictly optional: if the Langfuse keys are absent or the service is
unreachable, the app logs a warning and keeps working untraced. Observability
must never be able to take the application down.
"""

import logging

from config import get_settings

logger = logging.getLogger(__name__)

_handler = None
_initialised = False


def _init():
    global _handler, _initialised
    if _initialised:
        return
    _initialised = True

    settings = get_settings()
    if not settings.tracing_enabled:
        logger.info("Langfuse tracing disabled (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set).")
        return

    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        _handler = CallbackHandler()
        logger.info("Langfuse tracing enabled (%s).", settings.langfuse_host)
    except Exception as exc:
        logger.warning("Langfuse tracing unavailable, continuing without it: %s", exc)


def get_callbacks():
    """Callback list for LangChain/LangGraph config. Empty when tracing is off."""
    _init()
    return [_handler] if _handler else []


def build_run_config(thread_id, job_description):
    """Runnable config: checkpoint thread plus Langfuse trace metadata."""
    return {
        "configurable": {"thread_id": thread_id},
        "callbacks": get_callbacks(),
        "run_name": "job_chat_qa",
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_tags": ["job-chat", "with-jd" if job_description else "no-jd"],
            "jd_loaded": bool(job_description),
            "jd_words": len(job_description.split()) if job_description else 0,
        },
    }


def flush():
    """Flush pending traces before shutdown."""
    if not _handler:
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception as exc:
        logger.warning("Langfuse flush failed: %s", exc)
