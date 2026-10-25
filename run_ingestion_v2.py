"""CLI for the isolated agentic ingestion-v2 workflow."""

import argparse
import json
from pathlib import Path

from ingestion_v2.models import MappingPlan
from ingestion_v2.pipeline import AgenticIngestionPipeline
from ingestion_v2.tool_registry import tool_contracts_document


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Inspect, map, validate and optionally persist an unseen file"
    )
    parser.add_argument("--input", help="PDF, Excel, CSV or JSON input")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Explicitly enable validated MongoDB upserts; default is dry run",
    )
    parser.add_argument("--force-ocr", action="store_true")
    parser.add_argument(
        "--plan",
        help="Optional reviewed MappingPlan JSON; otherwise the local model proposes one",
    )
    parser.add_argument(
        "--print-tool-schemas",
        action="store_true",
        help="Print every ingestion-v2 tool input/output schema",
    )
    args = parser.parse_args(argv)
    if not args.print_tool_schemas and not args.input:
        parser.error("--input is required unless --print-tool-schemas is used")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.print_tool_schemas:
        print(json.dumps(tool_contracts_document(), indent=2, ensure_ascii=False))
        return 0
    plan = None
    if args.plan:
        plan = MappingPlan.model_validate_json(
            Path(args.plan).read_text(encoding="utf-8")
        )
    try:
        run = AgenticIngestionPipeline().run(
            args.input,
            write=args.write,
            force_ocr=args.force_ocr,
            plan=plan,
        )
    except Exception as exc:
        print(f"Status: failed\nError: {type(exc).__name__}: {exc}")
        return 1
    print(
        f"Status: {run.status.value}\n"
        f"Run ID: {run.run_id}\n"
        f"Target collection: {run.target_collection.value}\n"
        f"Valid records: {run.metrics.valid_records}/"
        f"{run.metrics.candidate_records}\n"
        f"Database write: {run.write_mode.value}\n"
        f"Evidence: artifacts/ingestion_v2/{run.run_id}/run.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
