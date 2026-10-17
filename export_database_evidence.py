"""Export a compact, source-traceable Phase 2 database evidence report."""

import argparse
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from pymongo import MongoClient


DATABASE_NAME = "bihar_agriculture"
PROVENANCE_FIELDS = (
    "extraction_run_id",
    "extracting_agent",
    "source_type",
    "extracted_at",
)
COLLECTION_PROJECTIONS = {
    "mandi_prices": {
        "_id": 0,
        "district": 1,
        "market": 1,
        "date": 1,
        "crop": 1,
        "variety": 1,
        "unit": 1,
        "source_url": 1,
        **{field: 1 for field in PROVENANCE_FIELDS},
    },
    "crop_statistics": {
        "_id": 0,
        "crop": 1,
        "season": 1,
        "year": 1,
        "area_unit": 1,
        "production_unit": 1,
        "yield_unit": 1,
        "source_file": 1,
        "source_row": 1,
        **{field: 1 for field in PROVENANCE_FIELDS},
    },
    "agriculture_documents": {
        "_id": 0,
        "source_id": 1,
        "document_title": 1,
        "page_number": 1,
        "chunk_index": 1,
        "language": 1,
        "extraction_method": 1,
        "source_url": 1,
        **{field: 1 for field in PROVENANCE_FIELDS},
    },
}
COLLECTION_SORTS = {
    "mandi_prices": [("date", -1), ("district", 1), ("crop", 1)],
    "crop_statistics": [("year", -1), ("crop", 1), ("season", 1)],
    "agriculture_documents": [
        ("source_id", 1),
        ("page_number", 1),
        ("chunk_index", 1),
    ],
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Export Phase 2 MongoDB population and provenance evidence."
    )
    parser.add_argument("--run-id", help="Supervisor run ID to include")
    parser.add_argument(
        "--output",
        default="docs/evidence/database_population_summary.json",
    )
    return parser.parse_args(argv)


def provenance_query():
    return {
        field: {"$exists": True, "$nin": [None, ""]}
        for field in PROVENANCE_FIELDS
    }


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def normalized_indexes(collection):
    indexes = []
    for name, details in sorted(collection.index_information().items()):
        indexes.append({
            "name": name,
            "keys": [list(item) for item in details.get("key", [])],
            "unique": bool(details.get("unique", False)),
        })
    return indexes


def collection_evidence(database, collection_name):
    collection = database[collection_name]
    total = collection.count_documents({})
    complete = collection.count_documents(provenance_query())
    cursor = collection.find(
        {}, COLLECTION_PROJECTIONS[collection_name]
    ).sort(COLLECTION_SORTS[collection_name]).limit(1)
    samples = list(cursor)
    return {
        "total_records": total,
        "records_with_complete_provenance": complete,
        "provenance_coverage": round(complete / total, 4) if total else 0,
        "indexes": normalized_indexes(collection),
        "representative_record": samples[0] if samples else None,
    }


def run_evidence(database, run_id=None):
    query = {"run_id": run_id} if run_id else {"dry_run": False}
    projection = {
        "_id": 0,
        "run_id": 1,
        "status": 1,
        "routing_strategy": 1,
        "requested_sources": 1,
        "dry_run": 1,
        "started_at": 1,
        "completed_at": 1,
        "automation_metrics": 1,
    }
    result = database["agent_runs"].find_one(
        query, projection, sort=[("started_at", -1)]
    )
    if result is None:
        requested = run_id or "latest non-dry run"
        raise ValueError(f"Agent run was not found: {requested}")
    return result


def build_report(database, run_id=None):
    collections = {
        name: collection_evidence(database, name)
        for name in COLLECTION_PROJECTIONS
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": DATABASE_NAME,
        "agent_run": run_evidence(database, run_id),
        "collections": collections,
        "all_records_have_provenance": all(
            item["total_records"]
            == item["records_with_complete_provenance"]
            for item in collections.values()
        ),
    }


def print_summary(report):
    print("\nPhase 2 database evidence")
    print("-------------------------")
    print(f"Run ID: {report['agent_run']['run_id']}")
    for name, details in report["collections"].items():
        percent = details["provenance_coverage"] * 100
        print(
            f"{name}: {details['records_with_complete_provenance']}/"
            f"{details['total_records']} records with provenance "
            f"({percent:.1f}%)"
        )
    verdict = "PASS" if report["all_records_have_provenance"] else "FAIL"
    print(f"Provenance completeness: {verdict}")


def main(argv=None):
    args = parse_args(argv)
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    client = MongoClient(uri)
    try:
        client.admin.command("ping")
        report = build_report(client[DATABASE_NAME], args.run_id)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
                default=json_value,
            )
            + "\n",
            encoding="utf-8",
        )
        print_summary(report)
        print(f"Evidence file: {output.resolve()}")
        return 0 if report["all_records_have_provenance"] else 1
    except Exception as exc:
        print(f"Database evidence export failed: {exc}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
