import unittest

from verify_phase6_dashboard import validate_snapshot


def snapshot():
    return {
        "summary": {
            "mandi_records": 6899,
            "dates_covered": 90,
            "markets": 49,
            "verified_locations": 42,
            "unresolved_locations": 7,
            "geospatial_coverage_percent": 85.7,
            "crop_statistics": 4372,
            "document_chunks": 153,
        },
        "series": {
            "daily_collection": [{"date": "2026-10-18", "records": 16}],
            "top_districts": [{"label": "Patna", "records": 10}],
            "top_crops": [{"label": "Potato", "records": 10}],
            "document_languages": [{"label": "hi", "records": 10}],
        },
        "geospatial": {
            "locations": [{"market_code": code} for code in range(42)],
        },
        "quality": {
            "price_completeness_percent": 100.0,
            "provenance_completeness_percent": 100.0,
            "coordinate_verification_percent": 85.7,
        },
    }


class Phase6DashboardVerificationTests(unittest.TestCase):
    def test_current_baseline_is_accepted(self):
        self.assertTrue(validate_snapshot(snapshot()))

    def test_inconsistent_coverage_is_rejected(self):
        value = snapshot()
        value["summary"]["geospatial_coverage_percent"] = 99.0
        with self.assertRaisesRegex(ValueError, "coverage percentage"):
            validate_snapshot(value)

    def test_empty_chart_series_is_rejected(self):
        value = snapshot()
        value["series"]["top_crops"] = []
        with self.assertRaisesRegex(ValueError, "top_crops"):
            validate_snapshot(value)


if __name__ == "__main__":
    unittest.main()
