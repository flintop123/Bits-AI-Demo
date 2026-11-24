"""Exercise PDF geometry, provenance, and fail-closed profile validation."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf as fitz
from pydantic import ValidationError

from ingestion_v2.pdf_table_models import ExtractPdfTableInput
from ingestion_v2.pdf_tables import extract_pdf_table, main, PdfTableValidationError


class PdfTableTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "fixture.pdf"

    def fixture(self, *, ruled=False, duplicate=False, value="78,26,998"):
        with fitz.open() as doc:
            page = doc.new_page(width=400, height=225)
            page.insert_text((20, 25), "Final crop report 2024-25")
            page.insert_text((20, 43), "Production in metric tonnes")
            if ruled:
                for x in (20, 125, 270, 380):
                    page.draw_line((x, 60), (x, 140))
                for y in (60, 80, 100, 120, 140):
                    page.draw_line((20, y), (380, y))
                lines = [
                    ("Crop", "Production", "Area (ha)"),
                    ("Rice", "9,934,021", "33,44,711"),
                    ("Wheat", value, "23,40,356"),
                    ("Wheat" if duplicate else "Maize", "6,602,964", "9,55,120"),
                ]
            else:
                lines = [
                    ("Crop", "Area", "Production (MT)"),
                    ("", "(ha)", ""),
                    ("Wheat", "23,40,356", value),
                    ("Wheat" if duplicate else "Rice", "33,44,711", "99,34,021"),
                ]
            for row, line in enumerate(lines):
                for col, text in enumerate(line):
                    if text:
                        x = (24, 143, 279)[col]
                        if not ruled and row >= 2 and col == 2:
                            x = 317  # Right-aligned numbers need not overlap header glyphs.
                        page.insert_text((x, 73 + row * 20), text)
            doc.save(self.path)
        profile = {
            "expected_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "page": 1,
            "strategy": "lines" if ruled else "positioned",
            "header_rows": 1 if ruled else 2,
            "row_label_header": "Crop",
            "rows": ["Wheat"],
            "columns": [
                {"key": "area", "header": "Area (ha)", "unit_text": "ha"},
                {"key": "production", "header": "Production (MT)", "unit_text": "MT"},
            ],
            "context": {"report": {"page": 1, "text": "Final crop report 2024-25"}},
        }
        if ruled:
            profile["context"]["production_unit"] = {
                "page": 1, "text": "Production in metric tonnes",
            }
            profile["columns"][1].update(
                header="Production", unit_text="metric tonnes", unit_context="production_unit",
            )
        else:
            profile.update(clip=[20, 60, 380, 145], x_edges=[20, 125, 270, 380])
        return profile

    def extract(self, profile):
        return extract_pdf_table(ExtractPdfTableInput(file_path=str(self.path), profile=profile))

    def test_positioned_multiline_header_indian_grouping_and_provenance(self):
        profile = self.fixture()
        result = self.extract(profile)
        area, production = result.values
        self.assertTrue(result.source_hash_match)
        self.assertEqual(result.source.source_hash, profile["expected_sha256"])
        self.assertEqual((area.value_decimal, production.value_decimal), ("2340356", "7826998"))
        self.assertEqual(len(area.column_header.boxes), 2)
        self.assertEqual(production.cell.text, "78,26,998")
        self.assertEqual(production.row_label.text, "Wheat")
        self.assertEqual(production.column_header.text, "Production (MT)")
        self.assertEqual(production.unit_as_reported, "MT")
        self.assertEqual(production.cell.page, 1)
        self.assertEqual(result.context["report"].text, "Final crop report 2024-25")

    @unittest.skipUnless(hasattr(fitz.Page, "find_tables"), "PyMuPDF Page.find_tables is unavailable")
    def test_independent_ruled_layout_swaps_columns_and_uses_source_unit_legend(self):
        profile = self.fixture(ruled=True, value="7,826,998.50")
        area, production = self.extract(profile).values
        self.assertEqual(area.value_decimal, "2340356")
        self.assertEqual(production.value_decimal, "7826998.50")
        self.assertEqual(production.unit_as_reported, "metric tonnes")
        self.assertEqual(production.unit_evidence.text, "Production in metric tonnes")
        self.assertLess(production.cell.boxes[0][0], area.cell.boxes[0][0])

    def test_different_bytes_disallowed_even_if_table_matches(self):
        profile = self.fixture()
        profile["expected_sha256"] = "0" * 64
        with self.assertRaisesRegex(PdfTableValidationError, "SHA-256 mismatch"):
            self.extract(profile)

    def test_duplicate_and_missing_rows_fail(self):
        profile = self.fixture(duplicate=True)
        with self.assertRaisesRegex(PdfTableValidationError, "found 2"):
            self.extract(profile)
        profile["rows"] = ["Barley"]
        with self.assertRaisesRegex(PdfTableValidationError, "found 0"):
            self.extract(profile)

    def test_malformed_grouping_is_rejected(self):
        with self.assertRaisesRegex(PdfTableValidationError, "invalid number"):
            self.extract(self.fixture(value="7,8,26998"))

    def test_unproven_context_unit_and_headers_fail(self):
        profile = self.fixture()
        profile["context"]["period"] = {"page": 1, "text": "2025-26"}
        with self.assertRaisesRegex(PdfTableValidationError, "period"):
            self.extract(profile)
        del profile["context"]["period"]
        profile["columns"][0]["unit_text"] = "tonnes"
        with self.assertRaisesRegex(PdfTableValidationError, "explicit unit"):
            self.extract(profile)
        profile["columns"][0]["header"] = "Yield (ha)"
        with self.assertRaisesRegex(PdfTableValidationError, "reviewed headers"):
            self.extract(profile)

    def test_invalid_clip_and_unknown_fields_rejected(self):
        profile = self.fixture()
        profile["x_edges"] = [20, 125, 120, 380]
        with self.assertRaises(ValidationError):
            self.extract(profile)
        with self.assertRaises(ValidationError):
            ExtractPdfTableInput(file_path=str(self.path), profile=self.fixture(), write=True)

    def test_cli_never_overwrites_evidence_or_accepts_write_flag(self):
        profile_path = self.root / "profile.json"
        profile_path.write_text(json.dumps(self.fixture()), encoding="utf-8")
        output = self.root / "output.json"
        args = ["--input", str(self.path), "--profile", str(profile_path), "--output", str(output)]
        with redirect_stdout(StringIO()):
            self.assertEqual(main(args), 0)
        self.assertEqual(len(json.loads(output.read_text(encoding="utf-8"))["values"]), 2)
        before = output.read_bytes()
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            main(args)
        self.assertEqual(output.read_bytes(), before)
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            main([*args, "--write"])


if __name__ == "__main__":
    unittest.main()
