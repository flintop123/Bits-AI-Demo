import unittest
from pathlib import Path

from tools.excel_extractor.excel_extractory import (
    CropStatisticsExcelExtractor,
)


WORKBOOK = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "Crop wise Area Production & Yield.xlsx"
)


class CropStatisticsExcelExtractorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = CropStatisticsExcelExtractor().load(WORKBOOK)

    def test_expected_record_count_and_period(self):
        self.assertEqual(len(self.records), 4372)
        years = {record["year"] for record in self.records}
        self.assertEqual(len(years), 59)
        self.assertIn("1966-67", years)
        self.assertIn("2024-25", years)

    def test_identity_is_unique(self):
        identities = {
            (record["crop"], record["season"], record["year"])
            for record in self.records
        }
        self.assertEqual(len(identities), len(self.records))

    def test_advance_estimate_flag_is_limited_to_latest_year(self):
        for record in self.records:
            self.assertEqual(
                record["is_advance_estimate"],
                record["year"] == "2024-25",
            )

    def test_special_production_units_are_preserved(self):
        units = {
            record["crop"]: record["production_unit"]
            for record in self.records
            if record["crop"] in {"Cotton", "Jute", "Sannhemp"}
        }
        self.assertEqual(units["Cotton"], "bale_170_kg")
        self.assertEqual(units["Jute"], "bale_180_kg")
        self.assertEqual(units["Sannhemp"], "bale_180_kg")


if __name__ == "__main__":
    unittest.main()
