import unittest
from unittest.mock import Mock

from phase4.mandi_orchestrator import (
    DailyMandiOrchestrator,
    normalize_api_record,
)


RAW_RECORD = {
    "id": "official-id",
    "marketCenterCode": 10026,
    "marketCenter": "हरनौत (नया)",
    "arrivalDate": 1792281600000,
    "arrivalQuantity": 2.0,
    "arrivalUnit": "Metric Tonnes",
    "commodityCode": 35,
    "commodity": "बैंगन",
    "varietyCode": 3500001,
    "variety": "Round",
    "gradeCode": 5,
    "grade": None,
    "minPrice": 5000.0,
    "maxPrice": 5000.0,
    "modalPrice": 5000.0,
    "priceTrend": 0.0,
    "priceUnit": "Rs/Quintal",
    "additionalFields": {"districtLg": "209", "district": "नालन्दा"},
    "auditDetails": {"createdTime": 10, "lastModifiedTime": 20},
    "tenantId": "br",
    "rowVersion": 1,
}


class DailyMandiOrchestratorTests(unittest.TestCase):
    def test_normalization_preserves_spatial_temporal_and_source_fields(self):
        record = normalize_api_record(
            RAW_RECORD, run_id="run-1", collected_at="now"
        )
        self.assertEqual(record["date"], "2026-10-18")
        self.assertEqual(record["district_code"], "209")
        self.assertEqual(record["market_code"], 10026)
        self.assertEqual(record["crop_code"], 35)
        self.assertEqual(record["price"], 5000.0)
        self.assertEqual(record["source_record_id"], "official-id")
        self.assertEqual(record["temporal_granularity"], "day")
        self.assertEqual(record["spatial_granularity"], "market")

    def test_dry_run_does_not_require_database(self):
        client = Mock()
        client.fetch_day.return_value = {
            "records": [RAW_RECORD],
            "total_count": 1,
            "pages_fetched": 1,
        }
        trace = DailyMandiOrchestrator(
            client=client, sleeper=lambda _: None
        ).run(["2026-10-18"], dry_run=True)
        self.assertEqual(trace["status"], "completed")
        self.assertEqual(trace["metrics"]["records_processed"], 1)
        self.assertEqual(trace["metrics"]["inserted"], 0)

    def test_transient_failure_is_retried_and_recorded(self):
        client = Mock()
        client.fetch_day.side_effect = [
            RuntimeError("temporary"),
            {
                "records": [RAW_RECORD],
                "total_count": 1,
                "pages_fetched": 1,
            },
        ]
        trace = DailyMandiOrchestrator(
            client=client, sleeper=lambda _: None, max_retries=1
        ).run(["2026-10-18"], dry_run=True)
        self.assertEqual(trace["status"], "completed")
        self.assertEqual(trace["metrics"]["retries"], 1)
        self.assertEqual(trace["results"][0]["attempts"], 2)


if __name__ == "__main__":
    unittest.main()
