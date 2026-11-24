"""Append-only local audit evidence for ingestion-v2 runs."""

import json
from pathlib import Path

from ingestion_v2.models import IngestionRun, RunEvent, StageStatus


class LocalIngestionRunStore:
    def __init__(self, root="artifacts/ingestion_v2", *, on_event=None):
        self.root = Path(root)
        self.on_event = on_event

    def directory(self, run_id):
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def add_event(
        self,
        run,
        stage,
        status,
        message,
        *,
        tool_name=None,
        tool_version=None,
        metrics=None,
        error_type=None,
    ):
        event = RunEvent(
            sequence=len(run.events) + 1,
            stage=stage,
            status=StageStatus(status),
            tool_name=tool_name,
            tool_version=tool_version,
            message=message,
            metrics=metrics or {},
            error_type=error_type,
        )
        run.events.append(event)
        path = self.directory(run.run_id) / "events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                event.model_dump(mode="json"), ensure_ascii=False
            ) + "\n")
        self.save_run(run)
        if self.on_event is not None:
            self.on_event(run.run_id, event)
        return event

    def save_run(self, run: IngestionRun):
        path = self.directory(run.run_id) / "run.json"
        path.write_text(
            json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save_artifact(self, run_id, filename, value):
        path = self.directory(run_id) / filename
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return path
