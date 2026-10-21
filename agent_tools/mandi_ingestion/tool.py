"""@tool wrapper around phase4's daily mandi API orchestrator.

This wraps the official Bihar Krishi mandi price API client
(phase4/mandi_api_client.py) and orchestrator (phase4/mandi_orchestrator.py)
— the same agent, ``daily_mandi_api_agent``, that docs/source_agent_map.csv,
eval/phase2_metrics.csv, and eval/cases/daily_mandi_api_agent.json already
treat as the canonical mandi-price agent. This is deliberate: phase2's own
``MandiSourceAgent`` (``mandi_web_agent``, a Playwright scrape of the HTML
page, used by Phase2Supervisor's own `--source mandi` path) has no concept
of a date range and isn't the one measured/documented as the mandi source,
so it can't support a request like "last seven days" at all. That path is
untouched by this module.
"""

from langchain_core.tools import tool

from agent_tools._shared import extract_days, wants_dry_run
from phase4.mandi_api_client import BiharMandiApiClient
from phase4.mandi_orchestrator import DailyMandiOrchestrator
from run_phase4_mandi_pipeline import resolve_dates


@tool
def ingest_mandi_prices(instruction: str = "") -> str:
    """Fetch Bihar mandi (market) crop prices from the official paginated
    API and store them in MongoDB.

    Use this when the user asks to fetch, pull, load, or refresh mandi
    prices, optionally for a date range — e.g. "load the last seven days of
    mandi data via api" or "pull today's mandi prices". Mention "dry run"
    in the instruction to validate without writing to MongoDB.
    """
    try:
        days = extract_days(instruction, default=1)
        dates = resolve_dates(None, days)
        dry_run = wants_dry_run(instruction)

        database = None
        if not dry_run:
            from conn.mandi_observations import MandiObservationMongo

            database = MandiObservationMongo()

        orchestrator = DailyMandiOrchestrator(
            client=BiharMandiApiClient(), database=database
        )
        trace = orchestrator.run(dates, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 - surfaced as an Observation, not a crash
        return f"ERROR: mandi ingestion failed: {exc}"

    metrics = trace["metrics"]
    return (
        f"status={trace['status']}; "
        f"dates_requested={metrics['dates_requested']}; "
        f"dates_completed={metrics['dates_completed']}; "
        f"records_processed={metrics['records_processed']}; "
        f"inserted={metrics['inserted']}; "
        f"dry_run={dry_run}"
    )
