"""Read-only live verification for Phase 7 spatiotemporal intelligence."""

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from data_api import create_app
from services.agriculture_query_service import AgricultureQueryService


def verify(output_path):
    service = AgricultureQueryService()
    try:
        service.client.admin.command("ping")
        crop_rows = list(service.mandi_prices.aggregate([
            {"$match": {"source_type": "government_mandi_api", "price": {"$type": "number"}}},
            {"$group": {"_id": "$crop", "records": {"$sum": 1}}},
            {"$sort": {"records": -1, "_id": 1}},
            {"$limit": 1},
        ]))
        if not crop_rows or not crop_rows[0].get("_id"):
            raise RuntimeError("No official numeric mandi observations are available")
        crop = crop_rows[0]["_id"]
        result = service.market_intelligence(
            {"crop": crop}, 30, display_language="en"
        )
        summary = result["summary"]
        checks = {
            "observations_present": summary["observations"] > 0,
            "daily_series_present": len(result["daily_series"]) > 0,
            "market_comparison_present": len(result["market_comparison"]) > 0,
            "latest_matches_series": (
                summary["latest_average_price"]
                == result["daily_series"][-1]["average_modal_price"]
            ),
            "freshness_present": bool(result["freshness"]["latest_data_date"]),
            "methodology_present": all(
                key in result["methodology"]
                for key in ("window", "change", "volatility", "anomaly", "ranking")
            ),
        }
        catalog_started = time.perf_counter()
        bilingual_catalog = service.list_values("all")
        catalog_seconds = round(time.perf_counter() - catalog_started, 4)
        official_crops = set(bilingual_catalog["mandi_crops"])
        crop_options = bilingual_catalog["mandi_crop_options"]
        district_options = bilingual_catalog["district_options"]
        market_options = bilingual_catalog["market_options"]
        checks["dropdown_values_equal_live_database_catalog"] = (
            {item["value"] for item in crop_options} == official_crops
            and {item["value"] for item in district_options}
            == set(bilingual_catalog["districts"])
            and {item["value"] for item in market_options}
            == set(bilingual_catalog["markets"])
        )
        all_options = crop_options + district_options + market_options
        checks["english_display_labels_are_english"] = all(
            not re.search(r"[\u0900-\u097f]", item["labels"]["en"])
            for item in all_options
        )
        checks["hindi_display_labels_are_hindi"] = all(
            bool(re.search(r"[\u0900-\u097f]", item["labels"]["hi"]))
            for item in all_options
        )
        checks["catalog_source_is_persistent_mongodb_cache"] = (
            bilingual_catalog.get("catalog_source")
            == "mongodb_distinct_with_persistent_label_cache"
        )
        checks["cached_catalog_load_under_three_seconds"] = (
            catalog_seconds < 3.0
        )
        checks["localized_market_results_are_english"] = all(
            not re.search(
                r"[\u0900-\u097f]",
                f"{item.get('market_label', '')} "
                f"{item.get('district_label', '')}",
            )
            for item in result["market_comparison"]
        )
        checks["market_labels_never_use_semantic_translation"] = all(
            item["methods"]["en"] in {
                "official_catalog_label",
                "reviewed_bilingual_alias",
                "devanagari_transliteration",
            }
            for item in market_options
        )
        checks["market_labels_are_short_place_labels"] = all(
            len(item["labels"]["en"]) <= 60
            and len(item["labels"]["en"].split()) <= 8
            for item in market_options
        )
        bilingual_resolution = None
        available_crops = service.mandi_prices.distinct("crop")
        if "आलू" in available_crops:
            english_result = service.market_intelligence(
                {"crop": "Potato"}, 30
            )
            bilingual_resolution = english_result.get(
                "filter_resolution", {}
            ).get("crop")
            checks["english_hindi_filter_resolution"] = (
                english_result.get("filters", {}).get("crop") == "आलू"
                and english_result.get("summary", {}).get(
                    "observations", 0
                ) > 0
            )
        client = create_app(service).test_client()
        response = client.get(
            "/api/v1/mandi-intelligence",
            query_string={"crop": crop, "days": 30},
        )
        checks["api_status_200"] = response.status_code == 200
        evidence = {
            "phase": "Phase 7 spatiotemporal market intelligence",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "PASS" if all(checks.values()) else "FAIL",
            "selected_crop": crop,
            "checks": checks,
            "observed_summary": summary,
            "freshness": result["freshness"],
            "locality": result["locality"],
            "market_sample": result["market_comparison"][:5],
            "anomalies": result["anomalies"],
            "methodology": result["methodology"],
            "bilingual_resolution": bilingual_resolution,
            "dynamic_bilingual_catalog": {
                "source": bilingual_catalog["catalog_source"],
                "official_crop_count": len(official_crops),
                "official_district_count": len(district_options),
                "official_market_count": len(market_options),
                "load_seconds": catalog_seconds,
                "crop_options": crop_options,
                "district_options": district_options,
                "market_options": market_options,
            },
        }
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("\nPhase 7 spatiotemporal intelligence verification")
        print("------------------------------------------------")
        print(f"Selected crop: {crop}")
        print(f"Observations: {summary['observations']}")
        print(f"Dates / markets: {summary['dates']} / {summary['markets']}")
        print(f"Direction / change: {summary['direction']} / {summary['change_percent']}%")
        print(f"Volatility: {summary['daily_volatility_percent']}%")
        print(f"Anomaly days: {summary['anomaly_days']}")
        if bilingual_resolution:
            print(
                "Bilingual filter: "
                f"{bilingual_resolution['requested']} -> "
                f"{bilingual_resolution['resolved']} "
                f"({bilingual_resolution['method']})"
            )
        print(
            "Dynamic bilingual filters: "
            f"{len(official_crops)} crops, {len(district_options)} districts, "
            f"{len(market_options)} markets in {catalog_seconds:.4f}s"
        )
        print(f"Overall: {evidence['status']}")
        print(f"Evidence file: {output.resolve()}")
        if evidence["status"] != "PASS":
            raise SystemExit(1)
        return evidence
    finally:
        service.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="docs/evidence/phase7_spatiotemporal_intelligence_smoke.json",
    )
    args = parser.parse_args()
    verify(args.output)


if __name__ == "__main__":
    main()
