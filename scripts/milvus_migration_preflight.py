"""Count which project records need review before any new Milvus migration.

This is an inventory only. It has no write, export, credential, embedding,
or Zilliz code path.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from services.milvus_public_demo import REPORT, SOURCE, TITLE, public_passages


_DUMP = Path(__file__).resolve().parents[1] / "db" / "dump"
_DATABASE = "bihar_agriculture"
COLLECTIONS = ("agriculture_documents", "mandi_prices", "crop_statistics", "mandi_locations")
_INTERNAL = frozenset({
    "agent_runs", "mandi_ingestion_runs", "extractor_runs", "viva_document_uploads", "mandi_catalog_labels",
})
_PRICE_PUBLIC_LABELS = {
    "source_type": "government_mandi_api", "source_url": "https://www.biharkrishi.in/mandi",
}
_CROP_PUBLIC_LABELS = {
    "source_type": "excel", "source_file": "Crop wise Area Production & Yield.xlsx",
    "source": "Department of Agriculture & Farmers Welfare",
}
_COORDINATE_LABELS = {"verification_status": "verified"}
# We read only the named report's public-looking rows locally and compare the
# current bytes against the committed reviewed catalog; no source labels alone
# promote a record to the pilot scope.
_REPORT_LOOKUP = {"source_file": REPORT, "source_url": SOURCE, "document_title": TITLE}
_PROJECTED = {field: 1 for field in ("page_number", "chunk_index", "content")}
_PROJECTED["_id"] = 0
_REPORT_SCAN_LIMIT = 512


def _exact_identity(row, approved):
    page, chunk, text = row.get("page_number"), row.get("chunk_index"), row.get("content")
    if type(page) is int and type(chunk) is int and isinstance(text, str):
        if approved.get((page, chunk)) == text:
            return page, chunk
    return None


def _inventory(names, count, report_rows, mode):
    approved = public_passages()
    names = set(names)
    present = names & set(COLLECTIONS)
    excluded = names & _INTERNAL
    totals = {key: count(key, {}) if key in present else 0 for key in COLLECTIONS}
    found = Counter()
    mismatches = 0
    truncated = False
    if "agriculture_documents" in present:
        for index, row in enumerate(report_rows()):
            if index >= _REPORT_SCAN_LIMIT:
                truncated = True
                break
            identity = _exact_identity(row, approved)
            if identity is None:
                mismatches += 1
            else:
                found[identity] += 1
    duplicates = sum(n - 1 for n in found.values())
    safe_pilot = not truncated and not mismatches and not duplicates and found.keys() == approved.keys()
    return {
        "mode": mode,
        "database": _DATABASE,
        "collections_present": sorted(present),
        "records_in_inventoried_collections": totals,
        "known_internal_collection_count": len(excluded),
        "known_internal_records_count_only_never_export": sum(count(key, {}) for key in sorted(excluded)),
        "other_collections_not_opened": len(names - set(COLLECTIONS) - _INTERNAL),
        "existing_milvus_pilot": {
            "reviewed_report": REPORT,
            "expected_pinned_passages": len(approved),
            "unique_matching_passages": len(found),
            "unexpected_passages_with_same_source_identity": mismatches,
            "duplicate_exact_passages": duplicates,
            "scan_truncated": truncated,
            "exact_pilot_corpus_present": safe_pilot,
            "outside_pilot_scope": (
                totals["agriculture_documents"] - len(approved) if safe_pilot
                else totals["agriculture_documents"]
            ),
        },
        "structured_rows_for_separate_review_not_export_approved": {
            "official_source_label_mandi": (
                count("mandi_prices", _PRICE_PUBLIC_LABELS) if "mandi_prices" in present else 0
            ),
            "official_workbook_label_crop": (
                count("crop_statistics", _CROP_PUBLIC_LABELS) if "crop_statistics" in present else 0
            ),
            "verified_label_market_coordinates": (
                count("mandi_locations", _COORDINATE_LABELS) if "mandi_locations" in present else 0
            ),
        },
        "writes": 0,
        "exported_records": 0,
        "cloud_contacted": False,
    }


def _matches(row, constraints):
    return all(row.get(key) == value for key, value in constraints.items())


def bundled_inventory():
    snapshot = {}
    for collection in COLLECTIONS:
        with (_DUMP / f"{collection}.jsonl").open(encoding="utf-8") as handle:
            snapshot[collection] = [json.loads(line) for line in handle if line.strip()]

    def count(collection, constraints):
        return sum(_matches(row, constraints) for row in snapshot[collection])

    return _inventory(snapshot, count, lambda: (
        row for row in snapshot["agriculture_documents"] if _matches(row, _REPORT_LOOKUP)
    ), "bundled_snapshot_not_live")


def inventory_database(database):
    """Bounded, read-only preview. Unknown collections are never opened."""
    names = database.list_collection_names()

    def count(collection, constraints):
        return database[collection].count_documents(constraints)

    def report_rows():
        return database["agriculture_documents"].find(_REPORT_LOOKUP, _PROJECTED).limit(_REPORT_SCAN_LIMIT + 1)

    return _inventory(names, count, report_rows, "live_loopback_mongo_read_only")


def live_inventory(port):
    from pymongo import MongoClient, timeout

    # Opt-in only; never consult environment URLs, credentials, or a shared DB.
    with MongoClient(host="127.0.0.1", port=port, directConnection=True,
                     timeoutMS=15000, serverSelectionTimeoutMS=3500) as client, timeout(15):
        return inventory_database(client[_DATABASE])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Count only on this machine's local MongoDB")
    parser.add_argument("--port", type=int, help="Loopback MongoDB port (default 27017; requires --live)")
    args = parser.parse_args(argv)
    if args.port is not None and (not args.live or not 1 <= args.port <= 65535):
        parser.error("--port requires --live and a port from 1 to 65535")
    try:
        result = live_inventory(args.port or 27017) if args.live else bundled_inventory()
    except Exception:
        print("Preflight could not complete. Check the bundled files or the local MongoDB service. "
              "No records were exported or uploaded.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
