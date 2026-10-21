"""@tool wrapper around phase2.agents.GroundedQAAgent.

Core logic lives in phase2/agents.py and services/agriculture_qa_service.py
(Ollama-backed, allowlisted query planning plus grounded answer generation
over MongoDB); this module only adds the LLM-facing description. Unlike the
three ingestion tools above, this one is read-only and never writes to
MongoDB.
"""

from langchain_core.tools import tool

from agent_tools._shared import new_run_id
from phase2.agents import GroundedQAAgent


@tool
def ask_agriculture_question(question: str) -> str:
    """Answer a natural-language question about already-stored Bihar
    agriculture data: mandi prices, crop statistics, or indexed agriculture
    documents (English or Hindi).

    Use this for read-only questions about data that has already been
    ingested. Do not use this to fetch new data — use the ingestion tools
    for that instead.
    """
    try:
        agent = GroundedQAAgent(question)
        result = agent.execute(new_run_id())
    except Exception as exc:  # noqa: BLE001 - surfaced as an Observation, not a crash
        return f"ERROR: grounded QA failed: {exc}"

    summary = result.summary
    return (
        f"answer={summary.get('answer')} | "
        f"intent={summary.get('intent')} | "
        f"sources={summary.get('source_count')}"
    )
