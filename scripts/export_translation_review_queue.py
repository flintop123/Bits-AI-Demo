"""Export rejected model label proposals for explicit project review."""

import argparse
import json
import os
from pathlib import Path


def build_review_queue(documents):
    queue = []
    for document in documents:
        evidence_by_language = document.get("translation_evidence") or {}
        for target_language, primary in evidence_by_language.items():
            fallback = (primary or {}).get("agentic_fallback") or {}
            status = fallback.get("validation_status", "")
            proposed = fallback.get("proposed_label")
            if not proposed or not status.startswith("rejected_"):
                continue
            queue.append({
                "entity_type": document.get("entity_type"),
                "official_value": document.get("official_value"),
                "official_language": document.get("official_language"),
                "target_language": target_language,
                "proposed_label": proposed,
                "model_name": fallback.get("model_name"),
                "primary_validation_status": primary.get(
                    "validation_status"
                ),
                "agentic_validation_status": status,
                "round_trip_candidate": fallback.get(
                    "round_trip_candidate"
                ),
                "review_status": "pending",
            })
    return sorted(
        queue,
        key=lambda item: (
            str(item.get("entity_type") or ""),
            str(item.get("official_value") or ""),
            str(item.get("target_language") or ""),
        ),
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Export rejected bilingual proposals for human review"
    )
    parser.add_argument(
        "--uri",
        default=os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/"),
    )
    parser.add_argument(
        "--output",
        default="artifacts/translation_review_queue.json",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    from pymongo import MongoClient

    with MongoClient(args.uri, serverSelectionTimeoutMS=5000) as client:
        collection = client["bihar_agriculture"]["mandi_catalog_labels"]
        queue = build_review_queue(collection.find({}, {"_id": 0}))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Pending translation proposals: {len(queue)}")
    print(f"Review queue: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
