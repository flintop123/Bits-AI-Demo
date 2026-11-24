import unittest
from bson import Int64
from unittest.mock import Mock

from services.agriculture_query_service import AgricultureQueryService


class FakeCursor:
    def __init__(self, records):
        self.records = list(records)

    def sort(self, *args, **kwargs):
        return self

    def limit(self, value):
        self.records = self.records[:value]
        return self

    def __iter__(self):
        return iter(self.records)


class VisualDashboardTests(unittest.TestCase):
    def test_snapshot_combines_collection_quality_and_pipeline_metrics(self):
        service = AgricultureQueryService.__new__(AgricultureQueryService)
        service.mandi_prices = Mock()
        service.mandi_locations = Mock()
        service.mandi_runs = Mock()
        service.crop_statistics = Mock()
        service.agriculture_documents = Mock()

        service.mandi_prices.count_documents.side_effect = [6899, 6800, 6899]
        distinct_values = {
            "date": ["2026-10-17", "2026-10-18"],
            "market_code": [*range(1, 50), "", None, True, " 0001 ", "unknown", -1, 2.0],
            "district_code": list(range(38)),
            "crop_code": list(range(95)),
        }
        service.mandi_prices.distinct.side_effect = (
            lambda field, _query: distinct_values[field]
        )
        service.mandi_prices.aggregate.side_effect = [
            [{"date": "2026-10-18", "records": 16}],
            [{"label": "पटना", "records": 200, "market_count": 3}],
            [{"label": "आलू", "records": 300, "market_count": 5}],
        ]
        point = {"type": "Point", "coordinates": [85.1, 25.6]}
        locations = [
            {"market_code": code, "market_name": "पटना", "district_name": "पटना", "location": point}
            for code in [" 0001 ", *map(Int64, range(2, 43)), "1", 999, True, ""]
        ]
        locations.append({"market_code": 43, "location": {"type": "Point", "coordinates": [999, 99]}})
        service.mandi_locations.find.return_value = FakeCursor(locations)
        service.crop_statistics.count_documents.return_value = 4372
        service.agriculture_documents.count_documents.return_value = 153
        service.agriculture_documents.aggregate.return_value = [
            {"label": "hi", "records": 60},
            {"label": "en", "records": 93},
        ]
        service.mandi_runs.find.return_value = FakeCursor([{
            "run_id": "run-1",
            "status": "completed",
            "metrics": {
                "dates_requested": 7,
                "dates_completed": 7,
                "records_processed": 714,
            },
        }])

        result = service.dashboard_snapshot(days=30)

        self.assertEqual(result["summary"]["mandi_records"], 6899)
        self.assertEqual(result["summary"]["markets"], 49)
        self.assertEqual(result["summary"]["verified_locations"], 42)
        self.assertEqual(result["summary"]["unresolved_locations"], 7)
        self.assertEqual(
            result["summary"]["geospatial_coverage_percent"], 85.7
        )
        self.assertEqual(result["pipeline"]["recent_success_percent"], 100.0)
        self.assertEqual(result["quality"]["price_complete_records"], 6800)
        self.assertEqual(len(result["geospatial"]["locations"]), 42)
        self.assertEqual({row["market_code"] for row in result["geospatial"]["locations"]}, set(range(1, 43)))
        service.mandi_locations.count_documents.assert_not_called()


    def test_empty_market_coverage_never_counts_orphan_coordinates(self):
        service = AgricultureQueryService.__new__(AgricultureQueryService)
        service.mandi_prices = Mock()
        service.mandi_locations = Mock()
        service.mandi_prices.distinct.return_value = [None, "", False, "not a code"]
        self.assertEqual(service._dashboard_market_codes(), set())
        self.assertEqual(service._dashboard_verified_locations(set()), {})
        service.mandi_locations.find.assert_not_called()

    def test_market_detail_groups_readonly_and_applies_individual_verification(self):
        service = AgricultureQueryService.__new__(AgricultureQueryService)
        service.mandi_prices = Mock()
        service.mandi_locations = Mock()
        service.mandi_prices.aggregate.return_value = [
            {"market_code": Int64(1635), "market": "अरवल", "district": "अरवल", "records": 30},
            {"market_code": 1636, "market": "अन्य", "records": 8},
        ]
        service.mandi_locations.find.return_value = FakeCursor([
            {"market_code": " 001635 ", "location": {"type": "Point", "coordinates": [84.66, 25.24]}},
            {"market_code": 999, "location": {"type": "Point", "coordinates": [84.66, 25.24]}},
        ])
        result = service.dashboard_details("markets")
        self.assertEqual(result, {"section": "markets", "truncated": False, "rows": [
            {"market_code": "1635", "market": "अरवल", "district": "अरवल", "records": 30,
             "verification_status": "verified"},
            {"market_code": "1636", "market": "अन्य", "records": 8, "verification_status": "unresolved"},
        ]})
        self.assertEqual(service.mandi_prices.aggregate.call_args.args[0][-2], {"$limit": 201})
        service.mandi_prices.update_one.assert_not_called()
        service.mandi_locations.update_one.assert_not_called()

    def test_detail_sections_are_bounded_and_safe_on_empty_rows(self):
        service = AgricultureQueryService.__new__(AgricultureQueryService)
        service.mandi_prices = Mock()
        service.mandi_locations = Mock()
        service.crop_statistics = Mock()
        service.agriculture_documents = Mock()
        for collection in [service.mandi_prices, service.crop_statistics, service.agriculture_documents]:
            collection.aggregate.return_value = []
        for section in ["dates", "markets", "crop_statistics", "documents"]:
            result = service.dashboard_details(section, 14)
            self.assertEqual(result, {"section": section, "rows": [], "truncated": False})
        service.mandi_locations.find.assert_not_called()
        service.agriculture_documents.aggregate.return_value = [{"records": 1}] * 201
        result = service.dashboard_details("documents")
        self.assertEqual(len(result["rows"]), 200)
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
