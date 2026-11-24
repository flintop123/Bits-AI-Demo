"""Compare ten Phase III database answers with the checked-in baseline."""

import argparse
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
COLLECTIONS = {"agriculture_documents", "crop_statistics", "mandi_locations", "mandi_prices"}
MAX_ROWS = 100


def load_cases():
    return json.loads((HERE / "round2_demo_cases.json").read_text(encoding="utf-8"))


def load_dump(directory):
    dump = {}
    hashes = {}
    for collection in sorted(COLLECTIONS):
        path = directory / (collection + ".jsonl")
        raw = path.read_bytes()
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
        dump[collection] = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    return dump, hashes


def distance_km(a, b):
    """Spherical great-circle distance between (lon, lat) pairs."""
    lon_a, lat_a, lon_b, lat_b = map(math.radians, (*a, *b))
    h = (math.sin((lat_b - lat_a) / 2) ** 2
         + math.cos(lat_a) * math.cos(lat_b) * math.sin((lon_b - lon_a) / 2) ** 2)
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def matches(row, filters):
    for field, expected in filters.items():
        if field not in row:
            return False
        actual = row[field]
        if isinstance(expected, dict):
            if set(expected) != {"$gte", "$lte"}:
                raise ValueError("Only inclusive closed ranges are supported")
            if not isinstance(actual, type(expected["$gte"])) or not expected["$gte"] <= actual <= expected["$lte"]:
                return False
        elif actual != expected:
            return False
    return True


def dump_query(dump, case):
    near = case.get("near")
    result = []
    for row in dump[case["collection"]]:
        if not matches(row, case["filters"]):
            continue
        if near:
            point = row.get("location") or {}
            coordinates = point.get("coordinates") or []
            if point.get("type") != "Point" or len(coordinates) != 2:
                continue
            origin = (near["longitude"], near["latitude"])
            if distance_km(origin, coordinates) > near["radius_km"]:
                continue
        result.append(row)
        if len(result) > MAX_ROWS:
            break
    return result


def mongo_query(database, case):
    collection = database[case["collection"]]
    fields = case["fields"] + (["content"] if case.get("content_contains") else [])
    projection = {**dict.fromkeys(fields, 1), "_id": 0}
    filters = case["filters"]
    near = case.get("near")
    if near:
        # $geoNear needs the repository's existing 2dsphere index. Never create it here.
        return list(collection.aggregate([
            {"$geoNear": {
                "near": {"type": "Point", "coordinates": [near["longitude"], near["latitude"]]},
                "key": "location", "distanceField": "distance_m", "spherical": True,
                "maxDistance": near["radius_km"] * 1000, "query": filters,
            }},
            {"$limit": MAX_ROWS + 1},
            {"$project": projection},
        ], maxTimeMS=5000))
    return list(collection.find(filters, projection).max_time_ms(5000).limit(MAX_ROWS + 1))


def row_key(row):
    """Match numeric JSON/BSON values across int/float without conflating booleans."""
    return tuple(
        (key, ("number", val) if type(val) in (int, float) else (
            "other", json.dumps(val, ensure_ascii=False, sort_keys=True, default=str)
        ))
        for key, val in sorted(row.items())
    )


def check_case(case, records):
    data = [{field: row[field] for field in case["fields"] if field in row} for row in records]
    if case["id"] in {"Q03", "Q04"}:
        data.sort(key=lambda row: row.get("date", row.get("year", "")))
    expected = case["expected"]
    errors = []
    if len(records) > MAX_ROWS:
        errors.append(f"More than {MAX_ROWS} matching records")
    if Counter(map(row_key, data)) != Counter(map(row_key, expected)):
        errors.append("Observed projected rows differ from the pinned baseline")
    excerpts = {}
    for excerpt in case.get("content_contains", []):
        excerpts[excerpt] = (
            len(records) == 1 and excerpt in (records[0].get("content") or "")
        )
        if not excerpts[excerpt]:
            errors.append(f"Cannot find the pinned excerpt: {excerpt}")
    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "collection": case["collection"],
        "expected": expected,
        "observed": data,
        "verified_excerpts": excerpts,
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="use only read queries against the configured MongoDB")
    parser.add_argument("--dump-dir", type=Path, default=HERE.parent / "db" / "dump")
    parser.add_argument("--output", type=Path, help="optional new JSON evidence file")
    args = parser.parse_args(argv)
    cases = load_cases()
    if args.live:
        # Credentials, when needed, come from the environment and aren't printed.
        from pymongo import MongoClient
        client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
                             serverSelectionTimeoutMS=5000, socketTimeoutMS=7000)
        context = client
        database = client[os.getenv("MONGODB_DATABASE", "bihar_agriculture")]
        query = lambda case: mongo_query(database, case)
        hashes = None
    else:
        dump, hashes = load_dump(args.dump_dir)
        context = nullcontext()
        query = lambda case: dump_query(dump, case)
    results = []
    with context:
        for case in cases:
            try:
                results.append(check_case(case, query(case)))
            except Exception as exc:
                # Never write unfiltered exception text: it could include connection details.
                results.append({"id": case["id"], "status": "ERROR",
                                "error_type": type(exc).__name__})
    report = {
        "mode": "live_mongodb_read_only" if args.live else "historical_jsonl_rehearsal",
        "baseline": "Repository JSONL dump at ea663a7 (October-dated market examples)",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": hashes,
        "cases": results,
    }
    if args.output:
        try:
            with args.output.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2, default=str)
                handle.write("\n")
        except FileExistsError:
            parser.error("output already exists; choose a new evidence filename")
    else:
        for result in results:
            print(result["id"], result["status"],
                  "; ".join(result.get("errors", [])) or result.get("error_type", ""))
    passed = sum(r["status"] == "PASS" for r in results)
    print(f"{report['mode']}: {passed}/{len(results)} matched the pinned baseline.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
