import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from review_pending_source import review

STATE = "bihar_state_data_lab"
HORT = "bihar_horticulture_dynamic"
SEED = "bihar_seed_reports"
NASA = "nasa_appeears_modis"


class SourcePreflightTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def write(self, filename, value):
        path = self.folder / filename
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(value, encoding="utf-8")
        return path

    def test_state_lab_shows_schema_and_locators_without_values_or_absolute_path(self):
        path = self.write("crop.csv", "crop,season,year,area\nPrivate,W,2022-23,42\n")
        report = review(STATE, path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        origin_url="https://example.org/fixtures/crop")
        self.assertEqual(report["status"], "local_extraction_checked")
        self.assertTrue(report["matched_expected_sha256"])
        self.assertEqual(report["observed_source_fields"], ["area", "crop", "season", "year"])
        self.assertEqual(report["sample_record_locators"][0]["row_number"], 2)
        self.assertNotIn("Private", json.dumps(report))
        self.assertNotIn(str(self.folder), json.dumps(report))
        self.assertFalse(report["live_fetch_performed"])
        self.assertFalse(report["database_write_performed"])

    def test_horticulture_json_reports_skipped_non_object(self):
        report = review(HORT, self.write("hort.json", '{"records":[1,{"district":"सारण","area":7}]}'))
        self.assertEqual(report["status"], "extraction_with_warnings")
        self.assertEqual(report["sample_record_locators"][0]["json_path"], "$.records[1]")

    def test_horticulture_xlsx_keeps_sheet_location(self):
        from openpyxl import Workbook
        path = self.folder / "hort.xlsx"
        workbook = Workbook()
        workbook.active.title = "Export"
        workbook.active.append(["district", "area"])
        workbook.active.append(["Patna", 9])
        workbook.save(path)
        report = review(HORT, path)
        self.assertEqual(report["sample_record_locators"][0]["sheet_name"], "Export")

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF not installed")
    def test_seed_pdf_has_page_anchor(self):
        import fitz
        path = self.folder / "seed_report.pdf"
        doc = fitz.open()
        try:
            page = doc.new_page()
            for index in range(4):
                page.insert_text((60, 90 + 25 * index), "Synthetic seed report: inspected area in hectares. Wheat 120.",
                                 fontsize=12)
            doc.save(path)
        finally:
            doc.close()
        report = review(SEED, path)
        self.assertEqual(report["extraction_metrics"]["source_units_extracted"], 1)
        self.assertEqual(report["sample_record_locators"][0]["page_number"], 1)

    def test_nasa_checks_container_not_geographic_validity(self):
        path = self.write("preview.tif", b"II\x2a\x00\x08\x00\x00\x00")
        self.assertEqual(review(NASA, path)["status"], "signature_only")
        path = self.write("preview.nc", b"\x89HDF\r\n\x1a\n")
        self.assertIn("not verified", review(NASA, path)["container_signature"])
        path = self.write("preview.nc", "<html>Login page</html>")
        with self.assertRaisesRegex(ValueError, "signature"):
            review(NASA, path)

    def test_rejects_origin_secrets_wrong_hash_and_wrong_format(self):
        path = self.write("crop.csv", "crop,area\nRice,42\n")
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            review(STATE, path, origin_url="https://example.org/download?token=private")
        with self.assertRaisesRegex(ValueError, "SHA-256 did not match"):
            review(STATE, path, expected_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "local .pdf"):
            review(SEED, path)

    def test_rejects_malformed_exports(self):
        for value, message in [
            ("Crop,crop\nA,B\n", "duplicated"),
            ("crop,area\nA\n", "field count"),
            ("crop,area\n", "No usable"),
            ("<!doctype html>\n<html>Login</html>\n", "HTML"),
        ]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, message):
                review(STATE, self.write("crop.csv", value))
        with self.assertRaisesRegex(ValueError, "duplicated"):
            review(HORT, self.write("hort.json", '[{"area":7,"area":8}]'))

    def test_explicit_plan_validates_without_db(self):
        def plan_fields():
            return [
                {"source_field": source, "target_field": target, "transformation": transform}
                for source, target, transform in [
                    ("crop", "crop", "text"), ("season", "season", "text"),
                    ("year", "year", "year"), ("area", "area_hectares", "number"),
                ]
            ]
        plan = self.write("plan.json", json.dumps({
            "target_collection": "crop_statistics",
            "field_mappings": plan_fields(),
            "identity_fields": ["crop", "season", "year"],
            "confidence": 1.0,
            "explanation": "Synthetic fixture crop statistics",
        }))
        sample = self.write("crop.csv", "crop,season,year,area\nRice,Kharif,2022-23,42\n")
        result = review(STATE, sample, plan=plan)
        self.assertEqual(result["status"], "local_mapping_validated")
        self.assertEqual(result["mapping"]["records_valid"], 1)
        self.assertFalse(result["database_write_performed"])
        sample = self.write("crop.csv", "crop,season,year,area\nRice,Kharif,2022-23,-1\n")
        self.assertEqual(review(STATE, sample, plan=plan)["status"], "local_mapping_needs_review")


if __name__ == "__main__":
    unittest.main()
