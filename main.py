"""Explicit entry points for the optional partner retrieval pipeline."""

import argparse
import json
import os
import uuid
from secrets import compare_digest
from threading import BoundedSemaphore

from flask import Flask, jsonify, request

from config_reader import read_config


def create_rag_app(config=None, *, rag=None, access_key=None):
    """Local, read-only QA; requests do not share stored conversation state."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 4096
    if rag is None:
        from rag import RagModel

        rag = RagModel(config=config or read_config(), stateless=True)
    if access_key is None:
        access_key = os.environ.get("AGRI_RAG_ACCESS_KEY", "")
    slots = BoundedSemaphore(2)

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error="Question payload is too large."), 413

    @app.route("/bihar-crop-chatbot/ask", methods=["GET", "POST"])
    def ask_question():
        if access_key and not compare_digest(
            request.headers.get("Authorization", "").encode("utf-8"),
            f"Bearer {access_key}".encode("utf-8"),
        ):
            return jsonify(error="Authentication required."), 401
        if request.method == "POST":
            payload = request.get_json(silent=True)
            question = payload.get("question") if isinstance(payload, dict) else None
        else:
            question = request.args.get("question", "")
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
            return jsonify(error="Question must be 1–500 characters."), 400
        if not slots.acquire(blocking=False):
            return jsonify(error="The QA service is busy. Please retry."), 429
        try:
            # Never accept a caller-selected checkpoint or claim chat memory.
            output = rag.runnable.invoke(
                {"question": question.strip()},
                config={"configurable": {"thread_id": str(uuid.uuid4())}},
            )
        except Exception as exc:
            app.logger.warning("QA request failed (%s)", type(exc).__name__)
            return jsonify(error="Retrieval is not available. Check the local model and index."), 503
        finally:
            slots.release()
        response = jsonify(
            answer=output.get("answer", ""),
            questions=output.get("subQuestions", []),
            source=output.get("source", []),
            citations=output.get("citations", []),
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


def run_app(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    actions = parser.add_subparsers(dest="action", required=True)
    serve = actions.add_parser("serve", help="Serve local read-only Milvus QA")
    serve.add_argument("--port", type=int, default=5002)
    api = actions.add_parser("preview-api", help="Preview allowlisted JSON/HTML/text")
    api.add_argument("--url", required=True, action="append")
    api.add_argument("--write", action="store_true", help="Store raw evidence in MongoDB")
    pdf = actions.add_parser("preview-pdf", help="Extract PDF without changing source text")
    pdf.add_argument("--input", required=True)
    pdf.add_argument("--translate", action="store_true", help="Add unverified derived English text")
    pdf.add_argument("--force-ocr", action="store_true")
    pdf.add_argument("--write", action="store_true")
    sync = actions.add_parser("sync", help="Build a new immutable public-document Milvus corpus")
    sync.add_argument("--collection", required=True)
    sync.add_argument("--max-documents", type=int, default=2000)
    sync.add_argument("--write", action="store_true", help="Explicitly permit a new Milvus index")
    sync.add_argument("--allow-remote", action="store_true", help="Confirm writes to a configured remote destination")
    args = parser.parse_args(argv)
    config = read_config(args.config)
    ingestion = config.get("document_ingestion", {})
    try:
        if args.action == "serve":
            create_rag_app(config).run(
                host="127.0.0.1", port=args.port, debug=False, use_reloader=False,
            )
            return 0
        if args.action == "preview-api":
            from ingest_any_source import ingest_api_urls

            result = ingest_api_urls(
                args.url, allowed_hosts=ingestion.get("api_hosts", ()), write=args.write,
            )
        elif args.action == "preview-pdf":
            from ingest_any_source import ingest_pdf

            result = ingest_pdf(
                args.input, translate=args.translate, write=args.write, force_ocr=args.force_ocr,
            )
        else:
            from sync_mongodb_to_milvus import sync_mongodb_to_milvus

            result = sync_mongodb_to_milvus(
                config, collection_name=args.collection, write=args.write,
                allow_remote=args.allow_remote, max_documents=args.max_documents,
            )
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_app())
