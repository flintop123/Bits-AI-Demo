import unittest
from unittest.mock import Mock

from services.agriculture_query_service import AgricultureQueryService


class DistrictTrendServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = AgricultureQueryService.__new__(AgricultureQueryService)
        self.service.resolve_mandi_filters = lambda filters: (filters, {})
        self.service.mandi_prices = Mock()
        self.service.mandi_prices.find_one.return_value = {"date": "2026-01-04"}
        self.service.mandi_prices.aggregate.return_value = []

    def test_weekly_calendar_window_stratifies_by_crop_and_unit(self):
        self.service.find_district_trends({"district": "Arwal"}, "weekly", 2)
        pipeline = self.service.mandi_prices.aggregate.call_args.args[0]
        self.assertEqual(pipeline[0]["$match"]["date"]["$gte"], "2025-12-22")
        self.assertEqual(pipeline[0]["$match"]["date"]["$lte"], "2026-01-04")
        truncation = pipeline[1]["$set"]["period_date"]["$dateTrunc"]
        self.assertEqual(truncation["startOfWeek"], "Monday")
        self.assertEqual(truncation["date"]["$dateFromString"]["onError"], None)
        keys = pipeline[3]["$group"]["_id"]
        self.assertEqual(set(keys), {"district", "period", "crop", "unit"})
        self.assertEqual(pipeline[-1]["$project"]["observed_days"], {"$size": "$observed_dates"})

    def test_monthly_calendar_window_and_unit_filter(self):
        self.service.find_district_trends({"unit": "kg"}, "monthly", 3)
        pipeline = self.service.mandi_prices.aggregate.call_args.args[0]
        self.assertEqual(pipeline[0]["$match"]["date"]["$gte"], "2025-11-01")
        self.assertEqual(pipeline[0]["$match"]["unit"]["$regex"], "^kg$")
        truncation = pipeline[1]["$set"]["period_date"]["$dateTrunc"]
        self.assertEqual(truncation["unit"], "month")
        self.assertNotIn("startOfWeek", truncation)

    def test_valid_empty_query_returns_no_buckets(self):
        self.service.mandi_prices.find_one.return_value = None
        self.assertEqual(self.service.find_district_trends({}, "daily", 12), [])
        self.service.mandi_prices.aggregate.assert_not_called()
