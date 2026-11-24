"""@tool wrapper around phase2.agents.AgricultureDocumentsSourceAgent.

Core logic lives in phase2/agents.py and tools/pdf_extractor/ (pypdf with a
Tesseract hin+eng OCR fallback); this module only adds the LLM-facing
description. Source selection is intentionally not exposed as a second
argument here: a single free-text instruction keeps the tool reliable for a
small local model, and the default behaviour (all enabled manifest sources)
matches the existing ingest_agriculture_sources.py CLI with no filter.
"""

from langchain_core.tools import tool

from agent_tools._shared import ingestion_is_dry_run, new_run_id
from agent_tools.agent_logging import get_logger
from agent_tools.agriculture_documents_ingestion.selection import (
    select_pdf_sources,
)
from ingest_agriculture_sources import DEFAULT_MANIFEST, load_manifest
from phase2.agents import AgricultureDocumentsSourceAgent


@tool
def ingest_agriculture_documents(instruction: str = "") -> str:
    """Download and index the official Bihar / Government of India
    agriculture PDF documents (English or Hindi, including scanned
    documents that need OCR) into MongoDB's agriculture_documents
    collection.

    Use this when the user asks to fetch, ingest, index, or update official
    agriculture scheme, policy, or report PDFs. Pass the request text: the
    code narrows to specific PDFs by name/topic keyword or by "hindi" /
    "english"; with neither, all enabled PDFs are ingested. Mention "dry
    run" in the instruction to validate extraction without writing to
    MongoDB.
    """
    try:
        sources = load_manifest(DEFAULT_MANIFEST)
        selected, reason = select_pdf_sources(instruction, sources)
        if not selected:
            available = ", ".join(s["id"] for s in sources if s["enabled"])
            return (
                "ERROR: no enabled PDF matches that request. "
                f"Available sources: {available}"
            )
        selected_ids = [source["id"] for source in selected]
        get_logger().info(
            "PDF selection: %s -> %s", reason, ", ".join(selected_ids)
        )
        for source in selected:
            get_logger().info(
                "Parsing PDF: %s (%s) | %s",
                source["filename"], source["language"], source["url"],
            )
        agent = AgricultureDocumentsSourceAgent(source_ids=selected_ids)
        result = agent.execute(new_run_id(), dry_run=ingestion_is_dry_run(instruction))
    except Exception as exc:  # noqa: BLE001 - surfaced as an Observation, not a crash
        return f"ERROR: agriculture document ingestion failed: {exc}"

    summary = result.summary
    return (
        f"selected={','.join(selected_ids)}; "
        f"status={result.status}; "
        f"sources_processed={summary.get('sources_processed')}; "
        f"chunks_processed={summary.get('chunks_processed')}; "
        f"pages_extracted={summary.get('pages_extracted')}; "
        f"ocr_pages={summary.get('ocr_pages')}; "
        f"dry_run={summary.get('dry_run')}"
    )
