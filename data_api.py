"""Read-only HTTP API for Bihar agriculture data."""

import atexit
import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from services.agriculture_query_service import AgricultureQueryService
from services.multilingual_query_expansion import expand_document_query
from services.agriculture_qa_service import AgricultureQAService
from services.ollama_client import OllamaUnavailableError


def parse_limit(raw_limit):
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    return limit


def selected_filters(names):
    return {
        name: request.args.get(name, "").strip()
        for name in names
        if request.args.get(name, "").strip()
    }


def create_app(service=None, qa_service=None):
    app = Flask(__name__)
    query_service = service or AgricultureQueryService()
    if service is None:
        atexit.register(query_service.close)
    agriculture_qa = qa_service or AgricultureQAService(query_service)

    @app.errorhandler(ValueError)
    def handle_validation_error(error):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        app.logger.exception("Request failed")
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(OllamaUnavailableError)
    def handle_ollama_error(error):
        return jsonify({"error": str(error)}), 503

    @app.get("/health")
    def health():
        return jsonify(query_service.health())

    @app.get("/")
    def demo():
        return render_template("index.html")

    @app.get("/api/v1/mandi-prices")
    def mandi_prices():
        limit = parse_limit(request.args.get("limit", "20"))
        filters = selected_filters(
            ("district", "market", "crop", "variety", "date")
        )
        records = query_service.find_mandi_prices(filters, limit)
        return jsonify({
            "count": len(records),
            "filters": filters,
            "records": records,
        })

    @app.get("/api/v1/crop-statistics")
    def crop_statistics():
        limit = parse_limit(request.args.get("limit", "20"))
        filters = selected_filters(("crop", "season", "year"))
        records = query_service.find_crop_statistics(filters, limit)
        return jsonify({
            "count": len(records),
            "filters": filters,
            "records": records,
        })

    @app.get("/api/v1/catalog")
    def catalog():
        return jsonify(query_service.list_values())

    @app.get("/api/v1/documents/search")
    def document_search():
        limit = parse_limit(request.args.get("limit", "5"))
        search_terms = request.args.get("q", "").strip()
        expanded_terms = expand_document_query(
            search_terms, max_length=200
        )
        semantic_query = expand_document_query(
            search_terms, max_length=500
        )
        records = query_service.search_agriculture_documents(
            expanded_terms, limit, semantic_query=semantic_query
        )
        methods = sorted({
            method
            for record in records
            for method in record.get("retrieval", {}).get("methods", [])
        })
        return jsonify({
            "count": len(records),
            "query": search_terms,
            "expanded_query": expanded_terms,
            "retrieval": {
                "mode": (
                    "hybrid" if methods == ["keyword", "semantic"]
                    else (methods[0] if methods else "none")
                ),
                "methods": methods,
            },
            "records": records,
        })

    @app.post("/api/v1/ask")
    def ask_question():
        body = request.get_json(silent=True) or {}
        return jsonify(agriculture_qa.ask(
            body.get("question"),
            answer_language=body.get("answer_language", "auto"),
        ))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "5000")),
        debug=False,
    )
