"""Same-origin local dashboard endpoints for rehearsal and PDF intake."""

from hashlib import sha256
from ipaddress import ip_address
import logging
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from flask import Blueprint, Response, jsonify, request
from pymongo import timeout
from pymongo.errors import PyMongoError
from werkzeug.exceptions import RequestEntityTooLarge

from services.dashboard_document_chat import DashboardDocumentChat, DocumentChatUnavailable
from services.milvus_public_demo import DemoError
from services.viva_dashboard import (
    COLLECTION, Drafts, MAX_PDF_BYTES, ReactDashboard, ReactNoEvidence,
    UploadReadbackError, VivaUploadStore, preview_pdf,
)
from services.viva_evidence import (
    PAGE_ONLY, PageAnchors, answer_from_pdf, quote_is_in_passage, render_evidence_page,
)


VIVA_PREFIX = "/api/v1/viva"

_LOG = logging.getLogger(__name__)


class _DocumentChatBusy(RuntimeError):
    pass


class _DashboardQA:
    def __init__(self, qa, document_answer):
        self.qa, self.document_answer = qa, document_answer

    def ask(self, question, answer_language="auto"):
        return self.qa.ask(question, answer_language=answer_language, document_answer=self.document_answer)


def dashboard_question():
    body = request.get_json(silent=True)
    if (
        request.args or not isinstance(body, dict)
        or set(body) - {"question", "answer_language"}
        or not isinstance(body.get("question"), str)
    ):
        raise ValueError("Enter a question and optional answer language.")
    question = body["question"].strip()
    language = body.get("answer_language", "auto")
    if not 0 < len(question) <= 500 or language not in ("auto", "en", "hi"):
        raise ValueError("Enter 1–500 characters and choose a valid answer language.")
    return question, language


def viva_blueprint(qa, database, *, react=None, upload_store=None, document_chat=None, milvus_chat=None):
    bp = Blueprint("viva", __name__, url_prefix=VIVA_PREFIX)
    drafts, sources, worker = Drafts(), Drafts(), BoundedSemaphore(1)
    document_chat = document_chat if document_chat is not None else DashboardDocumentChat()
    chat_worker = BoundedSemaphore(1)
    milvus_worker = BoundedSemaphore(1)

    def answer_document(question, language):
        # Also callable inside LangGraph's tool thread: no Flask context is
        # needed here. Only this function acquires the shared chat slot.
        if not chat_worker.acquire(blocking=False):
            raise _DocumentChatBusy()
        try:
            return document_chat.ask(question, language)
        except DocumentChatUnavailable:
            raise
        except Exception as error:
            _LOG.warning("Document Chat failed (%s)", type(error).__name__)
            raise DocumentChatUnavailable(
                "Document Chat did not finish. Check local MongoDB and Ollama.",
            ) from None
        finally:
            chat_worker.release()

    dashboard_qa = _DashboardQA(qa, answer_document)
    react = react if react is not None else ReactDashboard(dashboard_qa)

    def store():
        return upload_store if upload_store is not None else VivaUploadStore(database())

    @bp.before_request
    def local_only():
        try:
            loopback = ip_address(request.remote_addr or "").is_loopback
            local_host = urlsplit(request.host_url).hostname in {"127.0.0.1", "localhost", "::1"}
        except ValueError:
            loopback = local_host = False
        origin = request.headers.get("Origin")
        if (not loopback or not local_host or
                (origin and origin != request.host_url.rstrip("/")) or
                request.headers.get("X-Agri-Dashboard") != "1"):
            return jsonify(error="Use the local dashboard to run this action."), 403
        if request.method == "POST" and not request.path.endswith(("/preview", "/attach")):
            request.max_content_length = 8192

    @bp.after_request
    def never_cache(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.errorhandler(RequestEntityTooLarge)
    def oversized(_error):
        return jsonify(error="The request is too large. PDF limit: 10 MiB."), 413

    @bp.errorhandler(PyMongoError)
    def mongo_unavailable(_error):
        return jsonify(error="MongoDB could not confirm the operation. Check MongoDB and retry or reopen the run ID."), 503

    @bp.errorhandler(UploadReadbackError)
    def verification_failed(error):
        return jsonify(error=str(error)), 409

    @bp.errorhandler(ReactNoEvidence)
    def missing_evidence(error):
        return jsonify(error=str(error)), 422

    @bp.errorhandler(_DocumentChatBusy)
    def document_chat_busy(_error):
        return jsonify(error="Document Chat is busy. Retry shortly."), 429

    @bp.errorhandler(DocumentChatUnavailable)
    def document_chat_unavailable(error):
        return jsonify(error=str(error)), 503

    @bp.post("/ask")
    def ask_direct():
        question, language = dashboard_question()
        return jsonify(dashboard_qa.ask(question, answer_language=language))

    @bp.post("/react")
    def ask_react():
        question, language = dashboard_question()
        if not worker.acquire(blocking=False):
            return jsonify(error="The dashboard is processing another request. Try again shortly."), 429
        try:
            return jsonify(react.ask(question, language))
        finally:
            worker.release()

    @bp.post("/document-chat")
    def ask_document_chat():
        return jsonify(answer_document(*dashboard_question()))

    @bp.post("/milvus-demo")
    def ask_milvus_demo():
        if milvus_chat is None:
            return jsonify(error="Start the opt-in Milvus dashboard to use this mode."), 503
        question, language = dashboard_question()
        if not milvus_worker.acquire(blocking=False):
            return jsonify(error="Milvus Vector RAG is busy. Retry shortly."), 429
        try:
            return jsonify(milvus_chat.ask(question, language))
        except ValueError:
            return jsonify(error="Milvus Vector RAG only accepts the supported public demo question in English."), 400
        except DemoError as error:
            return jsonify(error=str(error)), 503
        except Exception:
            return jsonify(error="Milvus Vector RAG did not complete. Check the approved collection and local Ollama. No other search was used."), 503
        finally:
            milvus_worker.release()

    def uploaded_pdf():
        request.max_content_length = MAX_PDF_BYTES + 64 * 1024
        request.max_form_memory_size = 256 * 1024
        request.max_form_parts = 4
        document = request.files.get("document")
        if document is None or not document.filename:
            raise ValueError("Choose a PDF to preview.")
        raw = document.stream.read(MAX_PDF_BYTES + 1)
        if len(raw) > MAX_PDF_BYTES:
            raise RequestEntityTooLarge()
        return document.filename, raw

    @bp.post("/uploads/preview")
    def preview_upload():
        filename, raw = uploaded_pdf()
        if not worker.acquire(blocking=False):
            return jsonify(error="The dashboard is processing another request. Try again shortly."), 429
        try:
            from pypdf.errors import PdfReadError
            from tools.pdf_extractor.agriculture_pdf_extractor import OCRUnavailableError

            try:
                result = preview_pdf(raw, filename,
                                     force_ocr=request.form.get("force_ocr") == "1")
            except OCRUnavailableError:
                raise ValueError("OCR is unavailable. Check the Tesseract installation and its Hindi/English languages.") from None
            except PdfReadError:
                raise ValueError("The PDF could not be extracted. Try a different copy or excerpt.") from None
            drafts.put(result)
            sources.set(result["run_id"], raw)
            return jsonify({**result, "status": "preview", "collection": COLLECTION,
                            "source_available": True})
        finally:
            worker.release()

    @bp.post("/uploads/<uuid:run_id>/react-preview")
    def react_ingestion_preview(run_id):
        if request.get_data() or request.args:
            raise ValueError("ReAct preview accepts only the reviewed upload run ID.")
        key = str(run_id)
        raw, draft = sources.get(key), drafts.get(key)
        if raw is None or draft is None:
            return jsonify(error="That upload preview expired. Upload the PDF again."), 404
        if sha256(raw).hexdigest() != draft["source_sha256"]:
            return jsonify(error="The cached PDF does not match the upload preview."), 409
        if not worker.acquire(blocking=False):
            return jsonify(error="The dashboard is busy. Retry the ReAct preview shortly."), 429
        try:
            return jsonify(react.preview_document_ingestion(raw, draft))
        finally:
            worker.release()

    @bp.post("/uploads/<uuid:run_id>/save")
    def save_upload(run_id):
        if request.content_length:
            raise ValueError("Save accepts only a reviewed run ID, not replacement records.")
        draft = drafts.get(str(run_id))
        with timeout(8):
            if draft is not None:
                stored = store().save(draft)
                raw = sources.get(str(run_id))
                if raw is not None and sha256(raw).hexdigest() == stored["source_sha256"]:
                    sources.set(stored["run_id"], raw)
                return jsonify(with_source(stored))
            stored = store().read(str(run_id))
        if stored is not None:
            return jsonify(with_source(stored))
        return jsonify(error="That preview expired. Upload the PDF and review it again."), 404

    @bp.get("/uploads/<uuid:run_id>")
    def read_upload(run_id):
        with timeout(8):
            stored = store().read(str(run_id))
        if stored is None:
            return jsonify(error="No saved MongoDB run with that ID."), 404
        return jsonify(with_source(stored))

    def with_source(result):
        return {**result, "source_available": sources.get(result["run_id"]) is not None}

    @bp.post("/uploads/<uuid:run_id>/attach")
    def attach_source(run_id):
        _, raw = uploaded_pdf()
        with timeout(8):
            stored = store().read(str(run_id))
        if stored is None:
            return jsonify(error="No saved MongoDB run with that ID."), 404
        if sha256(raw).hexdigest() != stored["source_sha256"]:
            return jsonify(error="This PDF is not byte-for-byte identical to the saved source."), 409
        sources.set(str(run_id), raw)
        return jsonify(with_source(stored))

    def matching_source(run_id):
        key = str(run_id)
        raw = sources.get(key)
        if raw is None:
            return None, None
        run = drafts.get(key)
        if run is None:
            with timeout(8):
                run = store().read(key)
        if run is None or sha256(raw).hexdigest() != run["source_sha256"]:
            return None, None
        return raw, run

    def page_image(raw, number, anchor):
        if not worker.acquire(blocking=False):
            return jsonify(error="The dashboard is busy. Retry the source view shortly."), 429
        try:
            return Response(render_evidence_page(raw, number, anchor),
                            mimetype="image/png", headers={"X-Source-Anchor": anchor["kind"]})
        finally:
            worker.release()

    @bp.get("/uploads/<uuid:run_id>/evidence/<int:page>/<int:chunk>")
    def passage_evidence(run_id, page, chunk):
        raw, run = matching_source(run_id)
        if run is None:
            return jsonify(error="Reattach the exact original PDF to inspect the source page."), 404
        record = next((record for record in run["records"]
                       if record["page_number"] == page and record["chunk_index"] == chunk), None)
        if record is None:
            return jsonify(error="That page and chunk do not belong to this run."), 404
        anchor = record.get("source_anchor")
        quote = request.args.get("quote")
        if quote is not None and (len(quote) > 450 or not quote_is_in_passage(quote, record["content"])):
            return jsonify(error="That quote does not match this passage."), 400
        if quote is not None:
            anchor = None  # Never present a passage-level mark as proof of a quote.
        if anchor is None and record["extraction_method"] == "pypdf":
            # Backward-compatible view of old saved runs; MongoDB is not changed.
            import pymupdf
            with pymupdf.open(stream=raw, filetype="pdf") as document:
                anchor = PageAnchors(document[page - 1]).locate(
                    quote if quote is not None else record["content"], excerpt=quote is None,
                )
            if quote is not None and anchor["kind"] == "exact_passage":
                anchor["kind"] = "exact_quote"
        return page_image(raw, page, anchor or PAGE_ONLY)

    @bp.get("/uploads/<uuid:run_id>/table-evidence/<int:table>/<int:cell>")
    def cell_evidence(run_id, table, cell):
        raw, run = matching_source(run_id)
        if run is None:
            return jsonify(error="Reattach the exact original PDF to inspect the table."), 404
        try:
            entry = run.get("tables", [])[table]["cells"][cell]
        except IndexError:
            return jsonify(error="That cell has no verified evidence."), 404
        return page_image(raw, entry["page_number"], entry["source_anchor"])

    @bp.post("/uploads/<uuid:run_id>/ask")
    def ask_uploaded_pdf(run_id):
        body = request.get_json(silent=True)
        question = body.get("question") if isinstance(body, dict) else None
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
            raise ValueError("Enter a question of 1–500 characters.")
        language = body.get("answer_language", "auto")
        if language not in ("auto", "en", "hi"):
            raise ValueError("Choose a valid answer language.")
        with timeout(8):
            run = store().read(str(run_id))
        if run is None:
            return jsonify(error="Save and verify this PDF before asking about it."), 404
        if not worker.acquire(blocking=False):
            return jsonify(error="The dashboard is busy. Retry your question shortly."), 429
        try:
            return jsonify(answer_from_pdf(question.strip(), run, answer_language=language))
        finally:
            worker.release()

    return bp
