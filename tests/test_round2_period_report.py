import csv
from io import StringIO
import unittest

from ingestion_v2.pdf_sections import heading_for_evidence, leading_heading
from ingestion_v2.period_report import preview_period_report
from scripts.export_mandi_period_report import FIELDS, period_rows


class PeriodReportTests(unittest.TestCase):
    def export(self, frequency, dates, **overrides):
        snapshot = {"district_trends": {
            "frequencies": {frequency: [{
                "period_start": day, "district": "Patna", "average_modal_price": "1250.50",
                "observation_count": 5,
            } for day in dates]},
            "crop": "Potato", "unit": "quintal", "source": "Synthetic fixture",
            "latest_observation_date": "2025-02-26",
        }}
        rows = period_rows(snapshot, frequency)
        stream = StringIO()
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows([{**row, **overrides} for row in rows])
        return stream.getvalue().encode("utf-8-sig")

    def test_exported_weekly_and_monthly_district_reports_stay_distinct(self):
        week = preview_period_report(self.export("weekly", ["2025-02-03"]), "weekly")
        month = preview_period_report(self.export("monthly", ["2025-02-01"]), "monthly")
        self.assertNotEqual(week["sha256"], month["sha256"])
        self.assertEqual(week["rows"][0]["period_end"], "2025-02-09")
        self.assertEqual(month["rows"][0]["period_end"], "2025-02-28")
        self.assertEqual(month["rows"][0]["average_modal_price_inr"], "1250.50")
        self.assertEqual(month["rows"][0]["source_line"], 2)
        self.assertFalse(week["database_writes"])

    def test_does_not_cross_load_or_duplicate_reports(self):
        with self.assertRaisesRegex(ValueError, "frequency"):
            preview_period_report(self.export("weekly", ["2025-02-03"]), "monthly")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            preview_period_report(self.export("weekly", ["2025-02-03", "2025-02-03"]), "weekly")

    def test_rejects_invalid_start_nonfinite_price_and_unproven_count(self):
        with self.assertRaisesRegex(ValueError, "Monday"):
            preview_period_report(self.export("weekly", ["2025-02-04"]), "weekly")
        with self.assertRaisesRegex(ValueError, "first day"):
            preview_period_report(self.export("monthly", ["2025-02-02"]), "monthly")
        with self.assertRaisesRegex(ValueError, "finite"):
            preview_period_report(self.export("monthly", ["2025-02-01"], average_modal_price_inr="NaN"), "monthly")
        with self.assertRaisesRegex(ValueError, "positive"):
            preview_period_report(self.export("monthly", ["2025-02-01"], observation_count="0"), "monthly")

    def test_rejects_raw_mandi_rows_and_oversized_files(self):
        with self.assertRaisesRegex(ValueError, "headers"):
            preview_period_report(b"district,crop,price,date\nPatna,Potato,1000,2025-02-01", "monthly")
        with self.assertRaisesRegex(ValueError, "512 KiB"):
            preview_period_report(b"a" * (512 * 1024 + 1), "monthly")


class PdfSectionEvidenceTests(unittest.TestCase):
    def test_uses_only_heading_on_same_chunk_before_exact_quote(self):
        chunk = "1.10.4 Sugarcane\nOutlay is 508.46 lakh.\n1.11.2 Irrigation\nOutlay is 80 lakh."
        start = chunk.index("Outlay is 80")
        self.assertEqual(heading_for_evidence(chunk, start, start + len("Outlay is 80")), "1.11.2 Irrigation")
        self.assertIsNone(heading_for_evidence(chunk, None, None))
        self.assertIsNone(leading_heading(chunk))
        self.assertEqual(leading_heading(chunk.split("\n1.11.2", 1)[0]), "1.10.4 Sugarcane")

    def test_refuses_unanchored_spanning_and_decimal_lines(self):
        chunk = "Unknown section\nOutlay is 5.50.\n1.2 Horticulture\nReviewed report."
        self.assertIsNone(leading_heading(chunk))
        self.assertIsNone(leading_heading("65.01 crore.\nNo heading is stated."))
        self.assertIsNone(heading_for_evidence(chunk, chunk.index("Outlay"), len(chunk)))
