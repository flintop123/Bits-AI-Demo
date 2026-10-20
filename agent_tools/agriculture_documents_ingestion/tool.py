"""@tool wrapper around phase2.agents.AgricultureDocumentsSourceAgent.

Core logic lives in phase2/agents.py and tools/pdf_extractor/ (pypdf with a
Tesseract hin+eng OCR fallback); this module only adds the LLM-facing
description. Source selection is intentionally not exposed as a second
argument here: a single free-text instruction keeps the tool reliable for a
small local model, and the default behaviour (all enabled manifest sources)
matches the existing ingest_agriculture_sources.py CLI with no filter.
"""

from langchain_core.tools import tool

from agent_tools._shared import new_run_id, wants_dry_run
from phase2.agents import AgricultureDocumentsSourceAgent


@tool
def ingest_agriculture_documents(instruction: str = "") -> str:
    """Download and index the official Bihar / Government of India
    agriculture PDF documents (English or Hindi, including scanned
    documents that need OCR) into MongoDB's agriculture_documents
    collection.

    Use this when the user asks to fetch, ingest, index, or update official
    agriculture scheme, policy, or report PDFs. Mention "dry run" in the
    instruction to validate extraction without writing to MongoDB.
    """
    try:
        agent = AgricultureDocumentsSourceAgent()
        result = agent.execute(new_run_id(), dry_run=wants_dry_run(instruction))
    except Exception as exc:  # noqa: BLE001 - surfaced as an Observation, not a crash
        return f"ERROR: agriculture document ingestion failed: {exc}"

    summary = result.summary
    return (
        f"status={result.status}; "
        f"sources_processed={summary.get('sources_processed')}; "
        f"chunks_processed={summary.get('chunks_processed')}; "
        f"pages_extracted={summary.get('pages_extracted')}; "
        f"ocr_pages={summary.get('ocr_pages')}; "
        f"dry_run={summary.get('dry_run')}"
    )
