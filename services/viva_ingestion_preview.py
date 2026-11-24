"""Run the existing document source agent on one reviewed local PDF draft."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4


def run_document_ingestion_preview(raw, draft):
    """Stage one immutable PDF and call the real source agent in dry-run mode."""
    from phase2.agents import AgricultureDocumentsSourceAgent
    from services.viva_dashboard import MAX_PDF_BYTES, MAX_PDF_PAGES

    pages = draft["page_count"]
    if (not isinstance(raw, bytes) or not raw.startswith(b"%PDF-")
            or not 0 < len(raw) <= MAX_PDF_BYTES or not 1 <= pages <= MAX_PDF_PAGES):
        raise ValueError("The staged PDF does not match the validated upload.")
    digest = sha256(raw).hexdigest()
    if digest != draft["source_sha256"]:
        raise ValueError("The staged PDF does not match the validated upload.")

    # The stock ReAct CLI tool reads a fixed official-source manifest and can
    # download uncached files in dry-run mode. Instead, use its underlying
    # document agent with a private, single-source manifest. Its source
    # identity deliberately is not a URL: if the cache file disappears,
    # urllib.Request rejects it before urlopen or any proxy can be used.
    run_id = str(uuid4())
    source_id = "viva_uploaded_pdf"
    with TemporaryDirectory(prefix="agri-react-preview-") as directory:
        temp_dir = Path(directory)
        pdf = temp_dir / "upload.pdf"
        pdf.write_bytes(raw)
        manifest = temp_dir / "local-preview.json"
        manifest.write_text(json.dumps({"sources": [{
            "id": source_id,
            "title": "Dashboard uploaded PDF",
            "organization": "Local dashboard upload",
            "language": "mixed",
            "url": f"local-pdf-sha256-{digest}",
            "filename": pdf.name,
            "start_page": 1,
            "end_page": pages,
            "force_ocr": draft.get("force_ocr") is True,
        }]}), encoding="utf-8")
        if not pdf.is_file():
            raise ValueError("The staged PDF is unavailable.")
        source_agent = AgricultureDocumentsSourceAgent(
            manifest_path=manifest, source_ids=[source_id], download_directory=temp_dir,
        )
        try:
            result = source_agent.execute(run_id, dry_run=True)
        except (FileNotFoundError, ValueError):
            if not pdf.is_file():
                raise ValueError("The staged PDF is unavailable.") from None
            raise

    summary = result.summary
    if (
        result.status != "completed" or summary.get("dry_run") is not True
        or summary.get("sources_processed") != 1
        or any(summary.get(key) != 0 for key in ("inserted", "matched", "modified"))
    ):
        raise RuntimeError("The document preview could not confirm its dry-run result.")
    return {
        "status": "preview",
        "run_id": run_id,
        "source_sha256": digest,
        "source_file": draft["source_file"],
        "dry_run": True,
        "database_writes": False,
        "agent_id": result.agent_id,
        "extractor": result.tool_name,
        **{key: summary[key] for key in (
            "sources_processed", "pages_requested", "pages_extracted", "ocr_pages",
            "chunks_processed", "skipped_pages",
        )},
    }
