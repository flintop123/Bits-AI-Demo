import unittest

from scripts.build_github_pages_snapshot import (
    aggregate_record_counts,
    district_trend_snapshot,
)


class TemporalSpatialSnapshotTests(unittest.TestCase):
    def test_weekly_and_monthly_periods_are_calendar_aligned(self):
        records = [
            {"date": "2026-10-30", "records": 2},
            {"date": "2026-10-31", "records": 3},
            {"date": "2026-11-01", "records": 5},
        ]
        weekly = aggregate_record_counts(records, "weekly")
        monthly = aggregate_record_counts(records, "monthly")
        self.assertEqual(weekly, [{
            "period_start": "2026-10-26",
            "records": 10,
            "frequency": "weekly",
        }])
        self.assertEqual(
            [(item["period_start"], item["records"]) for item in monthly],
            [("2026-10-01", 5), ("2026-11-01", 5)],
        )

    def test_district_snapshot_retains_counts_and_average_prices(self):
        result = district_trend_snapshot([
            {
                "district": "Arwal", "date": "2026-10-30",
                "crop": "आलू", "price": 1000,
            },
            {
                "district": "Arwal", "date": "2026-10-31",
                "crop": "आलू", "price": 1200,
            },
        ])
        weekly = result["frequencies"]["weekly"]
        self.assertEqual(weekly[0]["average_modal_price"], 1100.0)
        self.assertEqual(weekly[0]["observation_count"], 2)
        self.assertEqual(result["source"], "db/dump/mandi_prices.jsonl")


if __name__ == "__main__":
    unittest.main()
