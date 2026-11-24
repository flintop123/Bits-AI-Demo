"""Same-origin local dashboard endpoints for rehearsal and PDF intake."""

from ipaddress import ip_address
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request
from pymongo import timeout
from pymongo.errors import PyMongoError
from werkzeug.exceptions import RequestEntityTooLarge

from services.viva_dashboard import (
    COLLECTION, Drafts, MAX_PDF_BYTES, ReactDashboard, ReactNoEvidence,
    UploadReadbackError, VivaUploadStore, preview_pdf,
)


VIVA_PREFIX = "/api/v1/viva"


def viva_blueprint(qa, database, *, react=None, upload_store=None):
    bp = Blueprint("viva", __name__, url_prefix=VIVA_PREFIX)
    drafts, worker = Drafts(), BoundedSemaphore(1)
    react = react if react is not None else ReactDashboard(qa)

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
        if request.method == "POST" and not request.path.endswith("/preview"):
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

    @bp.post("/react")
    def ask_react():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("question"), str):
            raise ValueError("A question is required.")
        question = body["question"].strip()
        language = body.get("answer_language", "auto")
        if not 0 < len(question) <= 500 or language not in ("auto", "en", "hi"):
            raise ValueError("Enter 1–500 characters and choose a valid answer language.")
        if not worker.acquire(blocking=False):
            return jsonify(error="The dashboard is processing another request. Try again shortly."), 429
        try:
            return jsonify(react.ask(question, language))
        finally:
            worker.release()

    @bp.post("/uploads/preview")
    def preview_upload():
        request.max_content_length = MAX_PDF_BYTES + 64 * 1024
        request.max_form_memory_size = 256 * 1024
        request.max_form_parts = 4
        document = request.files.get("document")
        if document is None or not document.filename:
            raise ValueError("Choose a PDF to preview.")
        raw = document.stream.read(MAX_PDF_BYTES + 1)
        if len(raw) > MAX_PDF_BYTES:
            raise RequestEntityTooLarge()
        if not worker.acquire(blocking=False):
            return jsonify(error="The dashboard is processing another request. Try again shortly."), 429
        try:
            from pypdf.errors import PdfReadError
            from tools.pdf_extractor.agriculture_pdf_extractor import OCRUnavailableError

            try:
                result = preview_pdf(raw, document.filename,
                                     force_ocr=request.form.get("force_ocr") == "1")
            except OCRUnavailableError:
                raise ValueError("OCR is unavailable. Check the Tesseract installation and its Hindi/English languages.") from None
            except PdfReadError:
                raise ValueError("The PDF could not be extracted. Try a different copy or excerpt.") from None
            drafts.put(result)
            return jsonify({**result, "status": "preview", "collection": COLLECTION})
        finally:
            worker.release()

    @bp.post("/uploads/<uuid:run_id>/save")
    def save_upload(run_id):
        if request.content_length:
            raise ValueError("Save accepts only a reviewed run ID, not replacement records.")
        draft = drafts.get(str(run_id))
        with timeout(8):
            if draft is not None:
                return jsonify(store().save(draft))
            stored = store().read(str(run_id))
        if stored is not None:
            return jsonify(stored)
        return jsonify(error="That preview expired. Upload the PDF and review it again."), 404

    @bp.get("/uploads/<uuid:run_id>")
    def read_upload(run_id):
        with timeout(8):
            stored = store().read(str(run_id))
        if stored is None:
            return jsonify(error="No saved MongoDB run with that ID."), 404
        return jsonify(stored)

    return bp
