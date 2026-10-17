"""Run and display the Phase 2 source-agent orchestration."""

import argparse
import json
import sys
from pathlib import Path

from config_reader import read_config
from phase2.agents import (
    AgricultureDocumentsSourceAgent,
    CropStatisticsSourceAgent,
    MandiSourceAgent,
)
from phase2.orchestrator import Phase2Supervisor
from phase2.run_store import MongoRunStore


SOURCE_CHOICES = ("mandi", "crop_statistics", "agriculture_documents")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run auditable Phase 2 agriculture source agents."
    )
    parser.add_argument(
        "--source", action="append", choices=SOURCE_CHOICES,
        help="Source agent to run. Repeat for multiple agents.",
    )
    parser.add_argument(
        "--document-source", action="append", dest="document_sources",
        help="Optional PDF source id from sources/agriculture_sources.yaml.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--trace-out", help="Optional path for the JSON trace.")
    return parser.parse_args(argv)


def build_supervisor(document_sources=None, run_store=None):
    config = read_config()
    agents = [
        MandiSourceAgent(config.get("bihar_krishi", {}).get("urls", [])),
        CropStatisticsSourceAgent(),
        AgricultureDocumentsSourceAgent(source_ids=document_sources),
    ]
    return Phase2Supervisor(
        agents,
        run_store=run_store or MongoRunStore(),
        max_retries=1,
    )


def print_summary(trace):
    print("\nPhase 2 agent orchestration summary")
    print("-----------------------------------")
    print(f"Run ID: {trace['run_id']}")
    print(f"Status: {trace['status']}")
    print(f"Routing: {trace['routing_strategy']}")
    for result in trace["results"]:
        print(
            f"{result['agent_id']}: {result['status']} "
            f"using {result['tool_name']}"
        )
    metrics = trace["automation_metrics"]
    print(
        "Automation: "
        f"{metrics['inputs_without_manual_intervention']}/"
        f"{metrics['inputs_attempted']} "
        f"({metrics['automation_rate'] * 100:.1f}%)"
    )
    print(f"Tool calls: {metrics['tool_calls']}; retries: {metrics['retries']}")
    if not trace["langsmith"]["enabled"]:
        print("LangSmith: instrumented, upload skipped (API key not configured)")
    else:
        print(
            "LangSmith: trace uploaded to project "
            f"{trace['langsmith']['project']}"
        )


def main(argv=None):
    try:
        args = parse_args(argv)
        sources = args.source or list(SOURCE_CHOICES)
        trace = build_supervisor(args.document_sources).run(
            sources,
            dry_run=args.dry_run,
            continue_on_error=not args.stop_on_error,
        )
        print_summary(trace)
        if args.trace_out:
            path = Path(args.trace_out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(trace, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"Trace file: {path.resolve()}")
        return 0 if trace["status"] == "completed" else 1
    except Exception as exc:
        print(f"Phase 2 orchestration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
