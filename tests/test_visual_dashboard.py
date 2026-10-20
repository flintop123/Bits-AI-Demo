import unittest
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
            "market_code": list(range(49)),
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
        service.mandi_locations.count_documents.return_value = 42
        service.mandi_locations.find.return_value = FakeCursor([{
            "market_code": 1,
            "market_name": "पटना",
            "district_name": "पटना",
            "location": {"type": "Point", "coordinates": [85.1, 25.6]},
        }])
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
        self.assertEqual(len(result["geospatial"]["locations"]), 1)


if __name__ == "__main__":
    unittest.main()
