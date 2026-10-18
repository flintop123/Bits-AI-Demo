"""Run scheduled or catch-up collection of Bihar mandi observations."""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from phase4.mandi_api_client import ALLOWED_PAGE_SIZES, BiharMandiApiClient
from phase4.mandi_orchestrator import DailyMandiOrchestrator


INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Collect date-bounded Bihar mandi prices via the public API."
    )
    parser.add_argument(
        "--date",
        action="append",
        dest="dates",
        help="Date to collect in YYYY-MM-DD format. Repeat as required.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Collect this many days ending today when --date is omitted.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        choices=ALLOWED_PAGE_SIZES,
        default=100,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--trace-out",
        default="artifacts/phase4/latest_mandi_run.json",
    )
    return parser.parse_args(argv)


def resolve_dates(values, days, *, today=None):
    if values:
        resolved = []
        for value in values:
            resolved.append(datetime.strptime(value, "%Y-%m-%d").date())
        return sorted(set(resolved))
    if days < 1 or days > 366:
        raise ValueError("--days must be between 1 and 366")
    today = today or datetime.now(INDIA_TIMEZONE).date()
    return sorted(today - timedelta(days=offset) for offset in range(days))


def print_summary(trace):
    print("\nPhase 4 daily mandi orchestration")
    print("---------------------------------")
    print(f"Run ID: {trace['run_id']}")
    print(f"Status: {trace['status']}")
    print(f"Agent: {trace['agent_id']}")
    print(f"Tool: {trace['tool_name']}")
    for result in trace["results"]:
        if result["status"] == "completed":
            print(
                f"{result['date']}: {result['records_processed']} records, "
                f"{result['pages_fetched']} page(s), "
                f"{result['districts']} districts, "
                f"{result['markets']} markets, "
                f"{result['commodities']} commodities, "
                f"inserted={result['inserted']}, "
                f"matched={result['matched']}, "
                f"modified={result['modified']}"
            )
        else:
            print(f"{result['date']}: FAILED — {result['error']}")
    metrics = trace["metrics"]
    print(
        "Automation: "
        f"{metrics['dates_completed']}/{metrics['dates_requested']} "
        f"({metrics['automation_rate'] * 100:.1f}%)"
    )
    print(f"Retries: {metrics['retries']}")
    if trace["dry_run"]:
        print("Database write: skipped (--dry-run)")


def main(argv=None):
    database = None
    try:
        args = parse_args(argv)
        dates = resolve_dates(args.dates, args.days)
        if not args.dry_run:
            from conn.mandi_observations import MandiObservationMongo
            database = MandiObservationMongo()
        trace = DailyMandiOrchestrator(
            client=BiharMandiApiClient(),
            database=database,
            page_size=args.page_size,
            max_retries=1,
        ).run(dates, dry_run=args.dry_run)
        print_summary(trace)
        output = Path(args.trace_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(trace, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"Trace file: {output.resolve()}")
        return 0 if trace["status"] == "completed" else 1
    except Exception as exc:
        print(f"Phase 4 mandi collection failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
