"""Verify the persisted Phase 5 mandi geospatial dataset and nearby query."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

from services.agriculture_query_service import AgricultureQueryService
from services.market_geocoding_service import BIHAR_BOUNDS


EXPECTED_MARKETS = 49
EXPECTED_VERIFIED = 42
EXPECTED_UNRESOLVED = 7
REJECTED_CROSS_DISTRICT_MARKET_CODE = "10025"
REQUIRED_INDEXES = {
    "unique_mandi_market_code": {"market_code": 1},
    "mandi_location_2dsphere": {"location": "2dsphere"},
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify Phase 5 geospatial persistence and retrieval."
    )
    parser.add_argument(
        "--dry-run-evidence",
        default="docs/evidence/phase5_all_markets_dry_run_v4.json",
    )
    parser.add_argument(
        "--live-write-evidence",
        default="docs/evidence/phase5_all_markets_live_write.json",
    )
    parser.add_argument(
        "--duplicate-evidence",
        default="docs/evidence/phase5_all_markets_duplicate_check.json",
    )
    parser.add_argument(
        "--output",
        default="docs/evidence/phase5_geospatial_final_summary.json",
    )
    parser.add_argument("--validate-dry-run-only", action="store_true")
    return parser.parse_args(argv)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _code(value):
    return str(value)


def validate_dry_run(report):
    expected = {
        "dry_run": True,
        "markets_considered": EXPECTED_MARKETS,
        "verified": EXPECTED_VERIFIED,
        "unresolved": EXPECTED_UNRESOLVED,
        "already_geocoded": 0,
    }
    for field, value in expected.items():
        if report.get(field) != value:
            raise ValueError(
                f"Dry-run {field} must be {value!r}; got {report.get(field)!r}"
            )
    verified = report.get("verified_locations", [])
    unresolved = report.get("unresolved_markets", [])
    if len(verified) != EXPECTED_VERIFIED:
        raise ValueError("Dry-run verified location details are incomplete")
    if len(unresolved) != EXPECTED_UNRESOLVED:
        raise ValueError("Dry-run unresolved market details are incomplete")
    unresolved_codes = {_code(item.get("market_code")) for item in unresolved}
    if REJECTED_CROSS_DISTRICT_MARKET_CODE not in unresolved_codes:
        raise ValueError(
            "Unsafe Bhagwanpur cross-district candidate was not rejected"
        )
    verified_codes = {_code(item.get("market_code")) for item in verified}
    if len(verified_codes) != EXPECTED_VERIFIED:
        raise ValueError("Dry-run verified market codes are not unique")
    if verified_codes & unresolved_codes:
        raise ValueError("A market cannot be both verified and unresolved")
    for record in verified:
        validate_location_record(record)
    return {
        "verified_codes": verified_codes,
        "unresolved_codes": unresolved_codes,
    }


def validate_live_write(report):
    expected = {
        "dry_run": False,
        "markets_considered": EXPECTED_MARKETS,
        "verified": EXPECTED_VERIFIED,
        "unresolved": EXPECTED_UNRESOLVED,
        "already_geocoded": 0,
    }
    for field, value in expected.items():
        if report.get(field) != value:
            raise ValueError(
                f"Live-write {field} must be {value!r}; got {report.get(field)!r}"
            )
    write = report.get("database_write", {})
    if write.get("inserted", 0) + write.get("matched", 0) != EXPECTED_VERIFIED:
        raise ValueError("Live write did not upsert all verified markets")


def validate_duplicate_check(report):
    expected = {
        "dry_run": False,
        "markets_considered": EXPECTED_MARKETS,
        "verified": 0,
        "unresolved": EXPECTED_UNRESOLVED,
        "already_geocoded": EXPECTED_VERIFIED,
    }
    for field, value in expected.items():
        if report.get(field) != value:
            raise ValueError(
                f"Duplicate check {field} must be {value!r}; "
                f"got {report.get(field)!r}"
            )
    write = report.get("database_write", {})
    if any(write.get(field, 0) for field in ("inserted", "matched", "modified")):
        raise ValueError("Duplicate check unexpectedly wrote location records")


def validate_location_record(record):
    if record.get("verification_status") != "verified":
        raise ValueError("Only verified location records are permitted")
    if record.get("location_precision") not in {
        "market_facility",
        "market_locality_centroid",
    }:
        raise ValueError("Location precision is missing or unsupported")
    location = record.get("location", {})
    if location.get("type") != "Point":
        raise ValueError("Location must be a GeoJSON Point")
    coordinates = location.get("coordinates", [])
    if len(coordinates) != 2:
        raise ValueError("GeoJSON coordinates must contain longitude and latitude")
    longitude, latitude = coordinates
    if not (
        BIHAR_BOUNDS["min_longitude"] <= longitude
        <= BIHAR_BOUNDS["max_longitude"]
        and BIHAR_BOUNDS["min_latitude"] <= latitude
        <= BIHAR_BOUNDS["max_latitude"]
    ):
        raise ValueError("Location falls outside the configured Bihar boundary")
    for field in (
        "market_code",
        "market_name",
        "district_name",
        "confidence",
        "coordinate_source",
        "coordinate_source_url",
        "coordinate_source_license",
    ):
        if record.get(field) in (None, ""):
            raise ValueError(f"Location record is missing {field}")


def validate_indexes(index_information):
    for name, expected_key in REQUIRED_INDEXES.items():
        index = index_information.get(name)
        if not index:
            raise ValueError(f"Required MongoDB index is missing: {name}")
        actual_key = dict(index.get("key", []))
        if actual_key != expected_key:
            raise ValueError(f"MongoDB index {name} has unexpected keys")
    if not index_information["unique_mandi_market_code"].get("unique"):
        raise ValueError("Market-code index must be unique")


def verify_database(database, expected_codes):
    locations = database["mandi_locations"]
    records = list(locations.find({}, {"_id": 0}))
    if len(records) != EXPECTED_VERIFIED:
        raise ValueError(
            f"Expected {EXPECTED_VERIFIED} stored locations; got {len(records)}"
        )
    actual_codes = {_code(item.get("market_code")) for item in records}
    if actual_codes != expected_codes:
        raise ValueError("Stored market codes differ from reviewed dry-run evidence")
    if REJECTED_CROSS_DISTRICT_MARKET_CODE in actual_codes:
        raise ValueError("Rejected cross-district market was written to MongoDB")
    coordinate_pairs = []
    precision_counts = {}
    for record in records:
        validate_location_record(record)
        coordinates = tuple(record["location"]["coordinates"])
        coordinate_pairs.append(coordinates)
        precision = record["location_precision"]
        precision_counts[precision] = precision_counts.get(precision, 0) + 1
    if len(set(coordinate_pairs)) != len(coordinate_pairs):
        raise ValueError("Stored market coordinates are unexpectedly duplicated")
    indexes = locations.index_information()
    validate_indexes(indexes)
    return records, precision_counts, sorted(REQUIRED_INDEXES)


def run_nearby_smoke(database, location_records):
    prices = database["mandi_prices"]
    chosen = None
    for location in location_records:
        if prices.find_one({"market_code": location["market_code"]}, {"_id": 1}):
            chosen = location
            break
    if chosen is None:
        raise ValueError("No stored market location has matching price observations")
    longitude, latitude = chosen["location"]["coordinates"]
    service = AgricultureQueryService(database=database)
    results = service.find_nearby_mandi_prices(
        latitude,
        longitude,
        5,
        {},
        365,
        20,
    )
    if not results:
        raise ValueError("Nearby price query returned no records")
    if not any(
        _code(item.get("market_code")) == _code(chosen["market_code"])
        for item in results
    ):
        raise ValueError("Nearby query did not return the origin market")
    if any(item.get("distance_km", 6) > 5 for item in results):
        raise ValueError("Nearby query returned a record outside the radius")
    sample = dict(results[0])
    return {
        "origin_market_code": chosen["market_code"],
        "origin_market_name": chosen["market_name"],
        "origin": {
            "type": "Point",
            "coordinates": [longitude, latitude],
        },
        "radius_km": 5,
        "days": 365,
        "records_returned": len(results),
        "sample": sample,
    }


def main(argv=None):
    args = parse_args(argv)
    dry_run_path = Path(args.dry_run_evidence)
    dry_run = load_json(dry_run_path)
    reviewed = validate_dry_run(dry_run)
    if args.validate_dry_run_only:
        print("Phase 5 reviewed dry-run evidence: PASS")
        print(f"Verified: {EXPECTED_VERIFIED}/{EXPECTED_MARKETS}")
        print(f"Unresolved by design: {EXPECTED_UNRESOLVED}")
        print("Unsafe Bhagwanpur cross-district match: rejected")
        return 0

    live_write_path = Path(args.live_write_evidence)
    duplicate_path = Path(args.duplicate_evidence)
    live_write = load_json(live_write_path)
    duplicate = load_json(duplicate_path)
    validate_live_write(live_write)
    validate_duplicate_check(duplicate)

    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    client = MongoClient(uri)
    try:
        client.admin.command("ping")
        database = client["bihar_agriculture"]
        records, precision_counts, indexes = verify_database(
            database, reviewed["verified_codes"]
        )
        nearby = run_nearby_smoke(database, records)
    finally:
        client.close()

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "reviewed_dry_run_evidence": str(dry_run_path),
        "live_write_evidence": str(live_write_path),
        "duplicate_check_evidence": str(duplicate_path),
        "coverage": {
            "markets_observed": EXPECTED_MARKETS,
            "verified_locations": EXPECTED_VERIFIED,
            "unresolved_not_guessed": EXPECTED_UNRESOLVED,
            "coverage_percent": round(EXPECTED_VERIFIED / EXPECTED_MARKETS * 100, 1),
            "precision_counts": precision_counts,
        },
        "database": {
            "collection": "mandi_locations",
            "record_count": len(records),
            "unique_market_codes": len(reviewed["verified_codes"]),
            "required_indexes": indexes,
            "rejected_cross_district_market_absent": True,
        },
        "idempotency": {
            "already_geocoded": duplicate["already_geocoded"],
            "database_write": duplicate["database_write"],
        },
        "nearby_query_smoke_test": nearby,
        "unresolved_market_codes": sorted(reviewed["unresolved_codes"]),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print("\nPhase 5 geospatial final verification")
    print("-------------------------------------")
    print("Status: PASS")
    print(f"Stored verified locations: {len(records)}")
    print(f"Coverage: {EXPECTED_VERIFIED}/{EXPECTED_MARKETS} (85.7%)")
    print(f"Unresolved and not guessed: {EXPECTED_UNRESOLVED}")
    print(f"Required indexes: {', '.join(indexes)}")
    print(
        "Nearby query: "
        f"{nearby['records_returned']} record(s) within {nearby['radius_km']} km"
    )
    print("Duplicate protection: PASS")
    print(f"Evidence file: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
