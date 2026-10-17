"""Shared Phase 2 orchestration data models."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentResult:
    agent_id: str
    source_id: str
    tool_name: str
    tool_input: dict[str, Any]
    status: str
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: str = field(default_factory=utc_now)
    completed_at: str | None = None

    def to_dict(self):
        return asdict(self)
