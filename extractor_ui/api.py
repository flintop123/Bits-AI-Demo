"""Flask blueprint for the extractor UI: the page, its assets and a small
JSON API. Local-only, with the same guard the viva dashboard uses."""

from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request, send_from_directory

from pymongo.errors import PyMongoError

from extractor_ui.history import RunHistoryStore
from extractor_ui.runner import MAX_REQUEST_CHARS, ExtractorRunner, RunnerBusy

EXTRACTOR_PREFIX = "/extractor"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def extractor_blueprint(runner=None, database=None):
    """``database`` is a zero-argument callable returning the MongoDB database;
    when given, finished runs are saved to and listed from ``extractor_runs``."""
    if runner is None:
        history = RunHistoryStore(database) if database is not None else None
        runner = ExtractorRunner(history=history)
    bp = Blueprint(
        "extractor_ui", __name__, url_prefix=EXTRACTOR_PREFIX,
        static_folder=str(STATIC_DIR), static_url_path="/assets",
    )

    @bp.before_request
    def local_only():
        try:
            loopback = ip_address(request.remote_addr or "").is_loopback
            local_host = urlsplit(request.host_url).hostname in {"127.0.0.1", "localhost", "::1"}
        except ValueError:
            loopback = local_host = False
        is_api = request.path.startswith(EXTRACTOR_PREFIX + "/api/")
        origin = request.headers.get("Origin")
        if (not loopback or not local_host or
                (is_api and ((origin and origin != request.host_url.rstrip("/")) or
                             request.headers.get("X-Agri-Dashboard") != "1"))):
            return jsonify(error="Use the local dashboard to run this action."), 403
        if request.method == "POST":
            request.max_content_length = 8192

    @bp.after_request
    def never_cache(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.get("/")
    def page():
        return send_from_directory(STATIC_DIR, "index.html")

    @bp.post("/api/runs")
    def start_run():
        body = request.get_json(silent=True) or {}
        text = body.get("request")
        dry_run = body.get("dry_run", False)
        if not isinstance(text, str) or not text.strip():
            return jsonify(error="Enter a request."), 400
        if len(text) > MAX_REQUEST_CHARS:
            return jsonify(error=f"Request is limited to {MAX_REQUEST_CHARS} characters."), 400
        if not isinstance(dry_run, bool):
            return jsonify(error="dry_run must be true or false."), 400
        try:
            run = runner.start(text.strip(), dry_run)
        except RunnerBusy:
            return jsonify(error="A run is already in progress."), 409
        return jsonify(run.snapshot()), 202

    @bp.get("/api/runs/latest")
    def latest_run():
        run = runner.latest()
        if run is None:
            return jsonify(error="No runs yet."), 404
        return jsonify(run.snapshot())

    @bp.get("/api/runs/<run_id>")
    def get_run(run_id):
        run = runner.get(run_id)
        if run is None:
            return jsonify(error="Unknown run."), 404
        after = request.args.get("after", default=0, type=int)
        return jsonify(run.snapshot(after))

    @bp.errorhandler(PyMongoError)
    def mongo_unavailable(_error):
        return jsonify(error="MongoDB could not be reached. Check that it is running."), 503

    @bp.get("/api/history")
    def history_page():
        if runner.history is None:
            return jsonify(error="Run history is not configured."), 503
        page = request.args.get("page", default=1, type=int)
        return jsonify(runner.history.page(page))

    @bp.get("/api/history/<run_id>")
    def history_detail(run_id):
        if runner.history is None:
            return jsonify(error="Run history is not configured."), 503
        document = runner.history.get(run_id)
        if document is None:
            return jsonify(error="Unknown run."), 404
        return jsonify(document)

    @bp.post("/api/runs/<run_id>/choice")
    def choose(run_id):
        run = runner.get(run_id)
        if run is None:
            return jsonify(error="Unknown run."), 404
        body = request.get_json(silent=True) or {}
        try:
            run.answer_prompt(body.get("choice"))
        except LookupError as exc:
            return jsonify(error=str(exc)), 409
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(ok=True)

    return bp