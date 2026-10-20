"""Enrich official Bihar mandi codes with verified GeoJSON coordinates."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient
import yaml

from conn.mandi_locations import MandiLocationMongo
from services.market_geocoding_service import (
    NOMINATIM_SEARCH_URL,
    NominatimGeocoder,
    SOURCE_LICENSE,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Geocode unique official Bihar mandi markets conservatively."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--market-code")
    parser.add_argument(
        "--output",
        default="docs/evidence/phase5_mandi_geocoding.json",
    )
    parser.add_argument(
        "--cache",
        default="artifacts/phase5/nominatim_cache.json",
    )
    parser.add_argument(
        "--aliases",
        default="sources/mandi_market_aliases.yaml",
    )
    return parser.parse_args(argv)


def load_aliases(path):
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {}
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported mandi alias manifest schema_version")
    aliases = {}
    for item in payload.get("aliases", []):
        code = str(item["market_code"])
        if code in aliases:
            raise ValueError(f"Duplicate mandi alias market_code: {code}")
        query_names = [
            str(value).strip()
            for value in item.get("query_names", [])
            if str(value).strip()
        ]
        if not query_names:
            raise ValueError(
                f"Mandi alias {code} must define at least one query name"
            )
        if not str(item.get("evidence_url") or "").startswith("https://"):
            raise ValueError(
                f"Mandi alias {code} must include HTTPS evidence"
            )
        item = {**item, "query_names": query_names}
        aliases[code] = item
    return aliases


def load_markets(database, market_code=None):
    query = {
        "market_code": {"$exists": True, "$ne": None},
        "source_type": "government_mandi_api",
    }
    if market_code is not None:
        values = [market_code]
        if str(market_code).isdigit():
            values.append(int(market_code))
        query["market_code"] = {"$in": values}
    pipeline = [
        {"$match": query},
        {"$sort": {"date": -1}},
        {"$group": {
            "_id": "$market_code",
            "market": {"$first": "$market"},
            "district": {"$first": "$district"},
            "district_code": {"$first": "$district_code"},
            "latest_observation_date": {"$first": "$date"},
        }},
        {"$sort": {"district": 1, "market": 1}},
    ]
    return [
        {
            "market_code": item["_id"],
            "market": item.get("market"),
            "district": item.get("district"),
            "district_code": item.get("district_code"),
            "latest_observation_date": item.get("latest_observation_date"),
        }
        for item in database["mandi_prices"].aggregate(pipeline)
    ]


def run(database, geocoder, *, dry_run=False, refresh=False, limit=None,
        market_code=None, aliases=None):
    location_store = MandiLocationMongo(database=database)
    markets = load_markets(database, market_code)
    aliases = aliases or {}
    for market in markets:
        alias = aliases.get(str(market["market_code"]))
        if alias:
            market["geocoding_aliases"] = alias.get(
                "query_names", [alias.get("query_name")]
            )
            market["geocoding_query_district"] = alias.get("query_district")
            market["geocoding_district_aliases"] = alias.get(
                "district_aliases", []
            )
            market["alias_evidence"] = alias.get("evidence_url")
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        markets = markets[:limit]
    existing = set()
    if not refresh:
        existing = set(location_store.collection.distinct("market_code"))

    accepted = []
    unresolved = []
    skipped = []
    for market in markets:
        if market["market_code"] in existing:
            skipped.append(market)
            continue
        decision = geocoder.geocode_market(market)
        evidence = {**market, **decision}
        if decision["status"] != "verified":
            unresolved.append(evidence)
            continue
        accepted.append({
            "market_code": market["market_code"],
            "market_name": market["market"],
            "district_code": market.get("district_code"),
            "district_name": market.get("district"),
            "location": decision["location"],
            "verification_status": "verified",
            "verification_method": "conservative_nominatim_match",
            "confidence": decision["confidence"],
            "display_name": decision.get("display_name"),
            "matched_district": decision.get("matched_district"),
            "osm_type": decision.get("osm_type"),
            "osm_id": decision.get("osm_id"),
            "place_type": decision.get("place_type"),
            "location_precision": decision["location_precision"],
            "resolution_reason": decision["resolution_reason"],
            "candidate_evidence": decision["top_candidates"],
            "geocoding_query": decision["query"],
            "geocoding_query_strategy": decision["query_strategy"],
            "alias_evidence": market.get("alias_evidence"),
            "geocoding_query_attempts": decision.get("query_attempts", []),
            "coordinate_source": "OpenStreetMap Nominatim",
            "coordinate_source_url": NOMINATIM_SEARCH_URL,
            "coordinate_source_license": SOURCE_LICENSE,
            "source_market_url": "https://www.biharkrishi.in/mandi",
            "latest_observation_date": market.get("latest_observation_date"),
        })

    write_result = {"inserted": 0, "matched": 0, "modified": 0}
    if not dry_run:
        write_result = location_store.upsert_verified(accepted)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "markets_considered": len(markets),
        "verified": len(accepted),
        "unresolved": len(unresolved),
        "already_geocoded": len(skipped),
        "database_write": write_result,
        "verified_locations": accepted,
        "unresolved_markets": unresolved,
    }


def main(argv=None):
    args = parse_args(argv)
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    client = MongoClient(uri)
    try:
        database = client["bihar_agriculture"]
        client.admin.command("ping")
        geocoder = NominatimGeocoder(cache_path=args.cache)
        report = run(
            database,
            geocoder,
            dry_run=args.dry_run,
            refresh=args.refresh,
            limit=args.limit,
            market_code=args.market_code,
            aliases=load_aliases(args.aliases),
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print("\nPhase 5 mandi geospatial enrichment")
        print("------------------------------------")
        print(f"Markets considered: {report['markets_considered']}")
        print(f"Verified locations: {report['verified']}")
        print(f"Unresolved (not guessed): {report['unresolved']}")
        print(f"Already geocoded: {report['already_geocoded']}")
        if args.dry_run:
            print("Database write: skipped (--dry-run)")
        else:
            print(f"New locations inserted: {report['database_write']['inserted']}")
            print(f"Existing locations matched: {report['database_write']['matched']}")
        print(f"Evidence file: {output.resolve()}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
