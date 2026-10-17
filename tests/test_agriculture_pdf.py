import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from ingest_agriculture_pdf import download_pdf, run_ingestion
from tools.pdf_extractor.agriculture_pdf_extractor import (
    AgriculturePDFExtractor,
)


class FakePage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class AgriculturePDFExtractorTests(unittest.TestCase):
    def test_extracts_selected_pages_with_traceable_metadata(self):
        reader = Mock()
        reader.pages = [
            FakePage("Cover"),
            FakePage("Rice seed replacement rate increased."),
            FakePage("Organic farming corridor along the Ganga."),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "source.pdf"
            path.write_bytes(b"%PDF-fixture")
            with patch(
                "tools.pdf_extractor.agriculture_pdf_extractor.PdfReader",
                return_value=reader,
            ):
                records = AgriculturePDFExtractor().load(
                    path,
                    source_url="https://example.test/source.pdf",
                    document_title="Official agriculture report",
                    start_page=2,
                    end_page=3,
                )

        self.assertEqual([record["page_number"] for record in records], [2, 3])
        self.assertTrue(all(record["source_file"] == "source.pdf" for record in records))
        self.assertTrue(all(record["content_hash"] for record in records))

    def test_normalizes_pdf_whitespace(self):
        text = "  Seed   development\n\n  Farm\tmechanization  "
        self.assertEqual(
            AgriculturePDFExtractor.normalize_text(text),
            "Seed development\nFarm mechanization",
        )

    def test_long_text_is_split_with_bounded_chunks(self):
        extractor = AgriculturePDFExtractor(chunk_size=200, chunk_overlap=20)
        chunks = extractor.chunk_text("word " * 180)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 200 for chunk in chunks))

    def test_invalid_page_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "PDF has 3 pages"):
            AgriculturePDFExtractor._validate_page_range(1, 4, 3)

    def test_existing_pdf_is_not_downloaded_again(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "source.pdf"
            path.write_bytes(b"%PDF-existing")
            with patch("ingest_agriculture_pdf.urlopen") as urlopen:
                resolved = download_pdf("https://example.test/a.pdf", path)
        self.assertEqual(resolved, path)
        urlopen.assert_not_called()

    def test_ingestion_summary_and_database_write(self):
        records = [
            {"page_number": 11, "character_count": 120},
            {"page_number": 12, "character_count": 80},
        ]
        extractor = Mock()
        extractor.load.return_value = records
        database = Mock()
        database.collection.count_documents.side_effect = [5, 7]
        database.upsert_records.return_value = {
            "inserted": 2,
            "matched": 0,
            "modified": 0,
        }

        summary = run_ingestion(
            "source.pdf",
            source_url="https://example.test/source.pdf",
            document_title="Report",
            start_page=11,
            end_page=12,
            database=database,
            extractor=extractor,
        )

        self.assertEqual(summary["pages_extracted"], 2)
        self.assertEqual(summary["chunks_processed"], 2)
        self.assertEqual(summary["characters_processed"], 200)
        self.assertEqual(summary["inserted"], 2)
        database.upsert_records.assert_called_once_with(records)


if __name__ == "__main__":
    unittest.main()
