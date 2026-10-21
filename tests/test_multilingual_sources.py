import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from ingest_agriculture_sources import (
    _configure_console_encoding,
    load_manifest,
    run_ingestion,
    select_sources,
)
from conn.agriculture_documents_mongodb import AgricultureDocumentsMongo
from tools.pdf_extractor.agriculture_pdf_extractor import (
    AgriculturePDFExtractor,
)


class FakePage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class MultilingualPDFExtractorTests(unittest.TestCase):
    def test_detects_hindi_english_and_mixed_text(self):
        detect = AgriculturePDFExtractor.detect_language
        self.assertEqual(detect("मखाना उत्पादन और खेती"), "hi")
        self.assertEqual(detect("Makhana production and cultivation"), "en")
        self.assertEqual(detect("मखाना Makhana उत्पादन crop"), "mixed")

    def test_normalizes_hindi_unicode_and_whitespace(self):
        value = "  मखाना\u00a0 उत्पादन  \n  बिहार\tकृषि "
        self.assertEqual(
            AgriculturePDFExtractor.normalize_text(value),
            "मखाना उत्पादन\nबिहार कृषि",
        )

    def test_sparse_page_uses_hindi_ocr_fallback(self):
        reader = Mock()
        reader.pages = [FakePage("")]
        extractor = AgriculturePDFExtractor()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "hindi.pdf"
            path.write_bytes(b"%PDF-fixture")
            with patch(
                "tools.pdf_extractor.agriculture_pdf_extractor.PdfReader",
                return_value=reader,
            ), patch.object(
                extractor,
                "_ocr_page",
                return_value="बिहार में मखाना उत्पादन महत्वपूर्ण है।",
            ):
                records = extractor.load(
                    path,
                    source_url="https://example.test/hindi.pdf",
                    document_title="मखाना रिपोर्ट",
                    declared_language="hi",
                )

        self.assertEqual(records[0]["language"], "hi")
        self.assertEqual(records[0]["extraction_method"], "tesseract_ocr")
        self.assertEqual(extractor.last_report["ocr_pages"], 1)

    def test_direct_hindi_text_does_not_require_ocr(self):
        text = "बिहार कृषि और मखाना उत्पादन की आधिकारिक जानकारी। " * 8
        reader = Mock()
        reader.pages = [FakePage(text)]
        extractor = AgriculturePDFExtractor()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "hindi.pdf"
            path.write_bytes(b"%PDF-fixture")
            with patch(
                "tools.pdf_extractor.agriculture_pdf_extractor.PdfReader",
                return_value=reader,
            ), patch.object(extractor, "_ocr_page") as ocr:
                records = extractor.load(
                    path,
                    source_url="https://example.test/hindi.pdf",
                    document_title="रिपोर्ट",
                    declared_language="hi",
                )

        ocr.assert_not_called()
        self.assertEqual(records[0]["extraction_method"], "pypdf")
        self.assertEqual(extractor.last_report["direct_pages"], 1)

    def test_short_valid_text_does_not_open_ocr_renderer(self):
        reader = Mock()
        reader.pages = [FakePage("Cover"), FakePage("Short policy note")]
        extractor = AgriculturePDFExtractor()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.pdf"
            path.write_bytes(b"%PDF-fixture")
            with patch(
                "tools.pdf_extractor.agriculture_pdf_extractor.PdfReader",
                return_value=reader,
            ), patch.object(extractor, "_ocr_page") as ocr:
                records = extractor.load(
                    path,
                    source_url="https://example.test/fixture.pdf",
                    document_title="Fixture",
                    start_page=1,
                    end_page=2,
                )

        ocr.assert_not_called()
        self.assertEqual(len(records), 2)


class SourceManifestTests(unittest.TestCase):
    def test_loads_utf8_manifest_and_selects_requested_source(self):
        manifest = """
sources:
  - id: hindi_source
    title: मखाना रिपोर्ट
    organization: Test Department
    language: hi
    url: https://example.test/hindi.pdf
    filename: hindi.pdf
    start_page: 2
    end_page: 4
    enabled: true
  - id: disabled_source
    title: Disabled
    organization: Test Department
    language: en
    url: https://example.test/disabled.pdf
    filename: disabled.pdf
    enabled: false
"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sources.yaml"
            path.write_text(manifest, encoding="utf-8")
            sources = load_manifest(path)

        self.assertEqual(sources[0]["title"], "मखाना रिपोर्ट")
        self.assertEqual(
            [source["id"] for source in select_sources(sources)],
            ["hindi_source"],
        )
        self.assertEqual(
            [source["id"] for source in select_sources(
                sources, ["disabled_source"]
            )],
            ["disabled_source"],
        )

    @patch("ingest_agriculture_sources.sys.stderr")
    @patch("ingest_agriculture_sources.sys.stdout")
    def test_console_streams_are_configured_for_utf8(
        self, stdout, stderr
    ):
        _configure_console_encoding()

        stdout.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="replace"
        )
        stderr.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="replace"
        )

    @patch("ingest_agriculture_sources.extract_source")
    def test_ingestion_preserves_multilingual_counts(self, extract_source):
        extract_source.return_value = (
            [{"character_count": 25}],
            {
                "pages_requested": 1,
                "pages_extracted": 1,
                "direct_pages": 0,
                "ocr_pages": 1,
                "skipped_pages": 0,
                "language_counts": {"hi": 1},
            },
        )
        database = Mock()
        database.collection.count_documents.side_effect = [54, 55]
        database.upsert_records.return_value = {
            "inserted": 1,
            "matched": 0,
            "modified": 0,
        }
        source = {
            "id": "hindi_source",
            "title": "मखाना रिपोर्ट",
            "organization": "Test Department",
            "language": "hi",
            "url": "https://example.test/hindi.pdf",
            "filename": "hindi.pdf",
            "start_page": 1,
            "end_page": 1,
            "enabled": True,
        }

        summary = run_ingestion([source], database=database)

        self.assertEqual(summary["inserted"], 1)
        self.assertEqual(summary["ocr_pages"], 1)
        self.assertEqual(summary["count_before"], 54)
        self.assertEqual(summary["count_after"], 55)


class MultilingualMongoIndexTests(unittest.TestCase):
    def test_language_metadata_is_not_used_as_mongodb_override(self):
        database = object.__new__(AgricultureDocumentsMongo)
        database.collection = Mock()
        database.collection.index_information.return_value = {
            "agriculture_document_text": {
                "default_language": "none",
                "language_override": "language",
            }
        }

        database._ensure_multilingual_text_index()

        database.collection.drop_index.assert_called_once_with(
            "agriculture_document_text"
        )
        database.collection.create_index.assert_called_once_with(
            [("content", "text"), ("document_title", "text")],
            name="agriculture_document_text",
            default_language="none",
            language_override="text_search_language",
        )


if __name__ == "__main__":
    unittest.main()
