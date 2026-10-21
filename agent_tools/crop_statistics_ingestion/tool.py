"""@tool wrapper around phase2.agents.CropStatisticsSourceAgent.

Core logic lives in phase2/agents.py (pandas/openpyxl extraction over the
committed workbook); this module only adds the LLM-facing description.
"""

from langchain_core.tools import tool

from agent_tools._shared import new_run_id, wants_dry_run
from phase2.agents import CropStatisticsSourceAgent


@tool
def ingest_crop_statistics(instruction: str = "") -> str:
    """Load the Bihar crop-wise area, production and yield workbook into
    MongoDB's crop_statistics collection.

    Use this when the user asks to update, refresh, or load crop area,
    production, or yield statistics. Mention "dry run" in the instruction
    to validate the extraction without writing to MongoDB.
    """
    try:
        agent = CropStatisticsSourceAgent()
        result = agent.execute(new_run_id(), dry_run=wants_dry_run(instruction))
    except Exception as exc:  # noqa: BLE001 - surfaced as an Observation, not a crash
        return f"ERROR: crop statistics ingestion failed: {exc}"

    summary = result.summary
    return (
        f"status={result.status}; "
        f"records_processed={summary.get('records_processed')}; "
        f"crop_groups={summary.get('crop_groups')}; "
        f"period={summary.get('period')}; "
        f"inserted={summary.get('inserted')}; "
        f"dry_run={summary.get('dry_run')}"
    )
