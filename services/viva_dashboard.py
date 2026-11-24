"""Local viva workflow: real retrieval, bounded PDF extraction, explicit save."""

from collections import OrderedDict
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic
from uuid import NAMESPACE_URL, uuid4, uuid5

from pymongo.errors import DuplicateKeyError

from ingestion_v2.extraction import extract_supported_file, inspect_input_file
from ingestion_v2.mapping import FIELD_TRANSFORMS, PLANNER_FIELDS, apply_mapping_plan
from ingestion_v2.models import (
    ExtractFileInput, FieldMapping, InspectFileInput, MappingPlan, MappingRequest,
    TargetCollection,
)
from services.viva_evidence import add_anchors, known_table_evidence


MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 25
MAX_RECORDS = 250
MAX_RECORD_BYTES = 2 * 1024 * 1024
COLLECTION = "viva_document_uploads"
TARGET = TargetCollection.AGRICULTURE_DOCUMENTS


def _record_bytes(records):
    return json.dumps(records, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def preview_pdf(raw, filename, *, force_ocr=False):
    """Extract and validate a PDF, without using a MongoDB connection."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    filename = "".join(c for c in Path(str(filename).replace("\\", "/")).name
                       if c.isprintable())
    if not filename.lower().endswith(".pdf") or not raw.startswith(b"%PDF-"):
        raise ValueError("Choose a valid PDF.")
    if not 0 < len(raw) <= MAX_PDF_BYTES:
        raise ValueError("The PDF must be at most 10 MiB.")
    filename = filename[:-4][:100] + ".pdf"
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError("Password-protected PDFs are not supported.")
        page_count = len(reader.pages)
        if not 1 <= page_count <= MAX_PDF_PAGES:
            raise ValueError(f"The PDF must have 1–{MAX_PDF_PAGES} pages.")
        for page in reader.pages:
            # Bound page rasterization if OCR is needed.
            scale = float(page.user_unit)
            w, h = float(page.mediabox.width) * scale, float(page.mediabox.height) * scale
            if not (0 < w <= 1600 and 0 < h <= 1600):
                raise ValueError("This PDF has an oversized or invalid page.")
    except (PdfReadError, TypeError, KeyError, RecursionError) as exc:
        raise ValueError("The PDF could not be opened.") from exc

    run_id = str(uuid4())
    source_hash = sha256(raw).hexdigest()
    source_ref = f"urn:sha256:{source_hash}"
    with TemporaryDirectory(prefix="agri-viva-") as temp:
        source = Path(temp) / "upload.pdf"
        source.write_bytes(raw)
        inspection = inspect_input_file(InspectFileInput(file_path=str(source)))
        inspection.source_file = filename
        extracted = extract_supported_file(
            ExtractFileInput(file_path=str(source), force_ocr=force_ocr)
        )
        tables, table_warnings = known_table_evidence(source, source_hash)
    if len(extracted.records) > MAX_RECORDS:
        raise ValueError(f"This PDF has more than {MAX_RECORDS} passages. Use a shorter excerpt.")
    for item in extracted.records:
        item.data.update(
            document_title=filename[:-4], source_file=filename,
            source_url=source_ref,
            content_hash=sha256(
                f"{source_ref}|{item.data['page_number']}|{item.data['chunk_index']}|"
                .encode("utf-8") + item.data["content"].encode("utf-8")
            ).hexdigest(),
        )
        for locator in [item.record_locator, *item.field_locators.values()]:
            locator.source_file = filename
            locator.source_url = source_ref

    plan = MappingPlan(
        target_collection=TARGET, confidence=1.0,
        explanation="Fixed PDF passage schema; text and locators come from the extractor.",
        field_mappings=[
            FieldMapping(source_field=key, target_field=key,
                         transformation=FIELD_TRANSFORMS.get(key, "identity"),
                         mapping_method="exact_name_schema_safeguard")
            for key in PLANNER_FIELDS[TARGET]
        ],
        identity_fields=["source_url", "page_number", "chunk_index"],
    )
    mapping = apply_mapping_plan(MappingRequest(
        run_id=run_id, inspection=inspection, extraction=extracted,
        allowed_collections=[TARGET],
    ), plan)
    valid, rejected = [], []
    for item in mapping.records:
        provenance = item.field_provenance.get("content")
        record = {key: item.data.get(key) for key in PLANNER_FIELDS[TARGET]}
        if (item.valid and provenance and
                provenance.locator.page_number == record["page_number"] and
                provenance.locator.chunk_index == record["chunk_index"] and
                record["content"]):
            valid.append(record)
        else:
            rejected.append({
                "page_number": record["page_number"], "chunk_index": record["chunk_index"],
                "errors": item.validation_errors or ["Missing or inconsistent source locator."],
            })
    add_anchors(raw, valid)
    if len(_record_bytes(valid)) + len(_record_bytes(tables)) > MAX_RECORD_BYTES:
        raise ValueError("The extracted text is too large for one demo run. Use a shorter excerpt.")
    return {
        "run_id": run_id, "source_file": filename, "source_sha256": source_hash,
        "page_count": page_count,
        "extracted_pages": extracted.metrics.source_units_extracted,
        "candidate_count": len(extracted.records), "valid_count": len(valid),
        "rejected": rejected, "warnings": [*extracted.warnings, *table_warnings],
        "schema": TARGET.value, "mapping": "fixed_pdf_passage_schema",
        "records": valid, "tables": tables,
    }


class Drafts:
    """Bounded, process-local drafts. A remote client cannot supply records."""

    def __init__(self, ttl=1800, limit=5):
        self.ttl, self.limit = ttl, limit
        self.items = OrderedDict()
        self.lock = Lock()

    def put(self, preview):
        self.set(preview["run_id"], preview)

    def set(self, key, value):
        with self.lock:
            self.items[key] = (monotonic() + self.ttl, value)
            self.items.move_to_end(key)
            while len(self.items) > self.limit:
                self.items.popitem(last=False)

    def get(self, run_id):
        with self.lock:
            entry = self.items.get(run_id)
            if entry and monotonic() < entry[0]:
                return entry[1]
            self.items.pop(run_id, None)
        return None


class UploadReadbackError(RuntimeError):
    pass


class VivaUploadStore:
    def __init__(self, database):
        self.database = database
        self.collection = database[COLLECTION]

    def save(self, preview):
        if not preview["records"]:
            raise ValueError("There are no validated records to save.")
        digest = sha256(_record_bytes(preview["records"])).hexdigest()
        source_hash = preview["source_sha256"]
        saved = self.collection.find_one(
            {"source_sha256": source_hash}, sort=[("saved_at", 1), ("_id", 1)],
        )
        if saved is not None:
            # Includes earlier random-ID uploads. Do not modify their data.
            return self._reuse(self._verified(saved), digest)

        # MongoDB's existing _id uniqueness also covers concurrent saves
        # from separate processes without a migration or a new index.
        saved_id = str(uuid5(NAMESPACE_URL, f"agriagent:viva:sha256:{source_hash}"))
        tables = preview.get("tables", [])
        table_digest = sha256(_record_bytes(tables)).hexdigest()
        try:
            update = self.collection.update_one(
                {"_id": saved_id},
                {"$setOnInsert": {
                    **preview, "run_id": saved_id, "records_sha256": digest,
                    "tables": tables, "tables_sha256": table_digest,
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
            inserted = update.upserted_id is not None
        except DuplicateKeyError:
            inserted = False
        result = self.read(saved_id)
        if not result or result["source_sha256"] != source_hash:
            raise UploadReadbackError("MongoDB did not confirm the reviewed source.")
        if not inserted:
            return self._reuse(result, digest)
        if result["records_sha256"] != digest or result["tables_sha256"] != table_digest:
            raise UploadReadbackError("The saved run did not match the reviewed evidence.")
        return {**result, "already_saved": False}

    @staticmethod
    def _reuse(result, digest):
        return {
            **result, "already_saved": True,
            "preview_matches_saved_passages": result["records_sha256"] == digest,
        }

    def read(self, run_id):
        stored = self.collection.find_one({"_id": run_id})
        if stored is None:
            return None
        return self._verified(stored)

    def _verified(self, stored):
        records = stored["records"]
        if (len(records) != stored["valid_count"] or
                sha256(_record_bytes(records)).hexdigest() != stored["records_sha256"]):
            raise UploadReadbackError("MongoDB read-back did not match the saved record count or hash.")
        if ("tables" in stored and
                sha256(_record_bytes(stored["tables"])).hexdigest() != stored.get("tables_sha256")):
            raise UploadReadbackError("MongoDB read-back did not match the saved table evidence hash.")
        return {
            **{key: value for key, value in stored.items() if key != "_id"},
            "status": "verified", "database": self.database.name,
            "collection": COLLECTION, "saved_count": len(records),
        }


class ReactDashboard:
    """Use the ReAct supervisor with exactly one grounded tool per request."""

    def __init__(self, qa, llm=None):
        self.qa, self.llm = qa, llm

    def ask(self, question, language):
        import httpx
        from langchain_core.tools import tool
        from langgraph.errors import GraphRecursionError
        from agent import build_agent
        from agent_config import get_chat_model
        from agent_tools.capabilities import resolve_request
        from services.ollama_client import OllamaUnavailableError

        resolution = resolve_request(question)
        if resolution.status != "resolved" or resolution.capability.domain != "question":
            raise ValueError(
                "ReAct here answers questions about stored data. Start with What, "
                "Show, Find or क्या. For a new PDF use Upload a PDF."
            )

        observed = None

        @tool("ask_agriculture_question", return_direct=True)
        def grounded_lookup() -> str:
            """Run grounded retrieval on the original question and return its answer."""
            nonlocal observed
            if observed is None:
                observed = self.qa.ask(question, answer_language=language)
            return str(observed["answer"])

        llm = self.llm
        unavailable = (httpx.HTTPError, ConnectionError)
        if llm is None:
            try:
                from ollama import ResponseError

                llm = get_chat_model(timeout=75, reasoning=False)
            except ImportError as exc:
                raise OllamaUnavailableError(
                    "ReAct could not initialize its Ollama client. Check the installation and loopback proxy settings."
                ) from exc
            unavailable += (ResponseError,)
        controller = build_agent(llm=llm, tools=[grounded_lookup])
        try:
            controller.invoke(
                {"messages": [{"role": "user", "content":
                    "Call ask_agriculture_question once for the following stored-data question.\n" + question}]},
                config={"recursion_limit": 5},
            )
        except unavailable as exc:
            raise OllamaUnavailableError("The ReAct model is unavailable. Check local Ollama.") from exc
        except GraphRecursionError as exc:
            if observed is None:
                raise ReactNoEvidence("ReAct did not reach the grounded tool within its step limit.") from exc
        if observed is None:
            raise ReactNoEvidence("ReAct did not call the grounded tool. Retry or use Direct QA.")
        # Display the actual tool observation, not a possibly embellished rewrite.
        return {**observed, "react": {
            "resolution": resolution.reason, "tool": grounded_lookup.name,
            "tool_called": True,
        }}


class ReactNoEvidence(RuntimeError):
    pass
