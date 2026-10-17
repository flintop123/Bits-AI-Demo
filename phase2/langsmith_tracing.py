"""Optional LangSmith tracing without making credentials mandatory."""

import os
from contextlib import nullcontext


def langsmith_status():
    enabled = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
    has_key = bool(os.getenv("LANGSMITH_API_KEY", "").strip())
    return {
        "enabled": enabled and has_key,
        "project": os.getenv("LANGSMITH_PROJECT", "bihar-crop-chatbot"),
        "reason": None if enabled and has_key else "LANGSMITH_API_KEY is not configured",
    }


def trace_context(name, *, run_type="chain", inputs=None, metadata=None):
    """Return a LangSmith trace context when configured, otherwise a no-op."""
    status = langsmith_status()
    if not status["enabled"]:
        return nullcontext()
    try:
        from langsmith.run_helpers import trace
    except ImportError:
        return nullcontext()
    return trace(
        name=name,
        run_type=run_type,
        inputs=inputs or {},
        metadata=metadata or {},
        project_name=status["project"],
    )
