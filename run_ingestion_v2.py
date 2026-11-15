"""CLI for the isolated agentic ingestion-v2 workflow."""

import argparse
import json
from pathlib import Path

from ingestion_v2.evidence_report import (
    compare_run_evidence,
    write_run_evidence_report,
)
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
    parser.add_argument(
        "--report-run",
        help="Generate an HTML/JSON evidence report for an existing run ID or directory",
    )
    parser.add_argument(
        "--compare-runs",
        nargs=2,
        metavar=("BEFORE_RUN", "AFTER_RUN"),
        help="Generate a quantitative before/after comparison for two run IDs or directories",
    )
    parser.add_argument(
        "--verify-mongo",
        action="store_true",
        help="Read back records tagged with the run ID from the allowlisted Mongo collection",
    )
    args = parser.parse_args(argv)
    modes = sum(bool(value) for value in (
        args.input,
        args.print_tool_schemas,
        args.report_run,
        args.compare_runs,
    ))
    if modes != 1:
        parser.error(
            "choose exactly one of --input, --print-tool-schemas, "
            "--report-run or --compare-runs"
        )
    return args


def _run_directory(value):
    supplied = Path(value)
    return supplied if supplied.is_dir() else Path("artifacts/ingestion_v2") / value


def main(argv=None):
    args = parse_args(argv)
    if args.print_tool_schemas:
        print(json.dumps(tool_contracts_document(), indent=2, ensure_ascii=False))
        return 0
    if args.report_run:
        result = write_run_evidence_report(
            _run_directory(args.report_run),
            verify_mongo=args.verify_mongo,
        )
        print(
            f"Evidence JSON: {result['json']}\n"
            f"Evidence HTML: {result['html']}\n"
            f"Mongo verification: "
            f"{result['report']['mongo_verification']['status']}"
        )
        return 0
    if args.compare_runs:
        before = _run_directory(args.compare_runs[0])
        after = _run_directory(args.compare_runs[1])
        output = (
            Path("artifacts/ingestion_v2/comparisons")
            / f"{before.name}_to_{after.name}"
        )
        result = compare_run_evidence(before, after, output)
        print(
            f"Comparison JSON: {result['json']}\n"
            f"Comparison HTML: {result['html']}\n"
            f"Result: {result['comparison']['conclusion']}"
        )
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
        f"Evidence: artifacts/ingestion_v2/{run.run_id}/run.json\n"
        f"Visual report: artifacts/ingestion_v2/{run.run_id}/evidence_report.html"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
