import unittest

from scripts.build_github_pages_snapshot import (
    aggregate_record_counts,
    district_trend_snapshot,
)


from scripts.export_mandi_period_report import period_rows


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
                "crop": "आलू", "unit": "quintal", "price": 1000,
            },
            {
                "district": "Arwal", "date": "2026-10-31",
                "crop": "आलू", "unit": "quintal", "price": 1200,
            },
            {"district": "Arwal", "date": "2026-10-31", "crop": "आलू", "unit": "kg", "price": 12},
            {"district": "Arwal", "date": "2026-10-31", "crop": "प्याज", "unit": "quintal", "price": 7500},
            {"district": "Arwal", "date": "invalid", "crop": "आलू", "unit": "quintal", "price": 9999},
            {"district": "Arwal", "date": "2026-10-31", "crop": "आलू", "price": 3000},
        ])
        self.assertEqual(result["unit"], "quintal")
        weekly = result["frequencies"]["weekly"]
        self.assertEqual(weekly[0]["average_modal_price"], 1100.0)
        self.assertEqual(weekly[0]["observation_count"], 2)
        self.assertEqual(result["source"], "db/dump/mandi_prices.jsonl")
        rows = period_rows({"district_trends": result}, "weekly")
        self.assertEqual(rows[0]["evidence_as_of"], "2026-10-31")
        self.assertEqual(rows[0]["average_modal_price_inr"], 1100.0)
        self.assertEqual(rows[0]["price_unit"], "quintal")

    def test_report_rejects_unavailable_data_and_unknown_frequency(self):
        snapshot = {"district_trends": district_trend_snapshot([])}
        with self.assertRaisesRegex(ValueError, "no district price data"):
            period_rows(snapshot, "monthly")
        with self.assertRaisesRegex(ValueError, "weekly or monthly"):
            period_rows(snapshot, "daily")


if __name__ == "__main__":
    unittest.main()
