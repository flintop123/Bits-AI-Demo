"""Run a live, read-only verification of the Phase 6 dashboard."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

from data_api import create_app
from services.agriculture_query_service import AgricultureQueryService


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify the live visual analytics dashboard."
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--output",
        default="docs/evidence/phase6_visual_dashboard_smoke.json",
    )
    return parser.parse_args(argv)


def validate_snapshot(snapshot):
    summary = snapshot.get("summary", {})
    minimums = {
        "mandi_records": 6899,
        "dates_covered": 90,
        "markets": 49,
        "verified_locations": 42,
        "crop_statistics": 4372,
        "document_chunks": 153,
    }
    for field, minimum in minimums.items():
        value = summary.get(field, 0)
        if value < minimum:
            raise ValueError(
                f"Dashboard {field} must be at least {minimum}; got {value}"
            )
    expected_unresolved = max(
        summary["markets"] - summary["verified_locations"], 0
    )
    if summary.get("unresolved_locations") != expected_unresolved:
        raise ValueError("Geospatial unresolved count is inconsistent")
    expected_coverage = round(
        summary["verified_locations"] / summary["markets"] * 100, 1
    )
    if summary.get("geospatial_coverage_percent") != expected_coverage:
        raise ValueError("Geospatial coverage percentage is inconsistent")
    series = snapshot.get("series", {})
    for name in (
        "daily_collection",
        "top_districts",
        "top_crops",
        "document_languages",
    ):
        if not series.get(name):
            raise ValueError(f"Dashboard series is empty: {name}")
    locations = snapshot.get("geospatial", {}).get("locations", [])
    if len(locations) != summary["verified_locations"]:
        raise ValueError("Dashboard location details are incomplete")
    quality = snapshot.get("quality", {})
    for name in (
        "price_completeness_percent",
        "provenance_completeness_percent",
        "coordinate_verification_percent",
    ):
        value = quality.get(name)
        if value is None or not 0 <= value <= 100:
            raise ValueError(f"Dashboard quality percentage is invalid: {name}")
    return True


def main(argv=None):
    args = parse_args(argv)
    if not 1 <= args.days <= 365:
        raise ValueError("days must be between 1 and 365")
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    client = MongoClient(uri)
    try:
        client.admin.command("ping")
        service = AgricultureQueryService(
            database=client["bihar_agriculture"]
        )
        snapshot = service.dashboard_snapshot(args.days)
        validate_snapshot(snapshot)
        app_client = create_app(service).test_client()
        api_response = app_client.get(f"/api/v1/dashboard?days={args.days}")
        page_response = app_client.get("/")
        css_response = app_client.get("/static/app.css")
        js_response = app_client.get("/static/app.js")
        if api_response.status_code != 200:
            raise ValueError("Dashboard API did not return HTTP 200")
        if page_response.status_code != 200 or b'id="dashboard"' not in page_response.data:
            raise ValueError("Dashboard page did not render correctly")
        if css_response.status_code != 200 or js_response.status_code != 200:
            raise ValueError("Dashboard static assets are unavailable")
    finally:
        client.close()

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "checks": {
            "mongodb_connection": True,
            "dashboard_snapshot": True,
            "dashboard_api_http_200": True,
            "dashboard_page_rendered": True,
            "static_assets_available": True,
            "all_series_nonempty": True,
            "quality_percentages_valid": True,
        },
        "observed": {
            "summary": snapshot["summary"],
            "quality": snapshot["quality"],
            "latest_run": snapshot["pipeline"]["latest_run"],
            "daily_points": len(snapshot["series"]["daily_collection"]),
            "district_bars": len(snapshot["series"]["top_districts"]),
            "crop_bars": len(snapshot["series"]["top_crops"]),
            "map_points": len(snapshot["geospatial"]["locations"]),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print("\nPhase 6 visual analytics verification")
    print("-------------------------------------")
    print("Status: PASS")
    print(f"Mandi observations: {snapshot['summary']['mandi_records']}")
    print(f"Dates covered: {snapshot['summary']['dates_covered']}")
    print(f"Observed markets: {snapshot['summary']['markets']}")
    print(f"Verified map points: {len(snapshot['geospatial']['locations'])}")
    print(f"Daily chart points: {len(snapshot['series']['daily_collection'])}")
    print("Dashboard API: HTTP 200")
    print("Page and static assets: PASS")
    print(f"Evidence file: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
