import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from conn.api_documents_mongodb import ApiDocumentsMongo
from ingest_any_source import (
    ingest_api_urls,
    ingest_pdf,
    translate_hindi_chunks,
)
from tools.api_extractor.generic_api import parse_api_response


class FakeTranslator:
    def __init__(self):
        self.inputs = []

    def translate(self, text):
        self.inputs.append(text)
        return "English translation"


class GenericApiReaderTests(unittest.TestCase):
    def test_reads_json_record_arrays_and_preserves_wrapper_metadata(self):
        kind, records = parse_api_response(
            '{"status":"ok","data":[{"id":1},{"id":2}]}',
            "application/json",
        )

        self.assertEqual(kind, "json")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["record"], {"id": 1})
        self.assertEqual(
            records[0]["response_metadata"],
            {"status": "ok"},
        )

    def test_reads_html_tables_and_non_table_text(self):
        kind, records = parse_api_response(
            "<table><tr><th>Market</th><th>Price</th></tr>"
            "<tr><td>Patna</td><td>1200</td></tr></table>",
            "text/html",
        )
        self.assertEqual(kind, "html_table")
        self.assertEqual(records[0]["Market"], "Patna")
        self.assertEqual(records[0]["Price"], "1200")

        kind, records = parse_api_response(
            "<html><body><p>API status is healthy</p></body></html>",
            "text/html",
        )
        self.assertEqual(kind, "html_text")
        self.assertEqual(records, [{"text": "API status is healthy"}])

    def test_rejects_malformed_json_response(self):
        with self.assertRaisesRegex(ValueError, "declared JSON"):
            parse_api_response("{invalid", "application/json")


class PdfTranslationTests(unittest.TestCase):
    def test_only_hindi_chunks_are_translated_and_original_is_retained(self):
        translator = FakeTranslator()
        records = [
            {"language": "hi", "content": "हिंदी पाठ"},
            {"language": "en", "content": "English text"},
        ]

        translated = translate_hindi_chunks(
            records,
            translator_factory=lambda: translator,
        )

        self.assertEqual(translator.inputs, ["हिंदी पाठ"])
        self.assertEqual(translated[0]["content"], "English translation")
        self.assertEqual(translated[0]["original_content"], "हिंदी पाठ")
        self.assertEqual(translated[0]["translation_language"], "en")
        self.assertEqual(translated[1], records[1])

    def test_does_not_load_translator_when_there_are_no_hindi_chunks(self):
        translator_factory = Mock()
        records = [{"language": "en", "content": "English text"}]

        self.assertIs(
            translate_hindi_chunks(records, translator_factory),
            records,
        )
        translator_factory.assert_not_called()

    def test_rejects_empty_translation_instead_of_saving_bad_text(self):
        translator = Mock()
        translator.translate.return_value = ""
        with self.assertRaisesRegex(RuntimeError, "returned empty content"):
            translate_hindi_chunks(
                [{"language": "hi", "content": "हिंदी पाठ"}],
                translator_factory=lambda: translator,
            )

    def test_pdf_ingestion_persists_translated_chunks(self):
        database = Mock()
        database.collection.count_documents.side_effect = [4, 5]
        database.upsert_records.return_value = {
            "inserted": 1,
            "matched": 0,
            "modified": 0,
        }
        extractor = Mock()
        extractor.load.return_value = [
            {
                "language": "hi",
                "content": "हिंदी पाठ",
                "page_number": 1,
                "chunk_index": 0,
            }
        ]
        extractor.last_report = {"language_counts": {"hi": 1}}

        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.pdf"
            path.write_bytes(b"%PDF-test")
            with unittest.mock.patch(
                "tools.pdf_extractor.agriculture_pdf_extractor."
                "AgriculturePDFExtractor",
                return_value=extractor,
            ):
                summary = ingest_pdf(
                    path,
                    database=database,
                    translator_factory=FakeTranslator,
                )

        persisted = database.upsert_records.call_args.args[0]
        self.assertEqual(persisted[0]["content"], "English translation")
        self.assertEqual(persisted[0]["original_content"], "हिंदी पाठ")
        self.assertEqual(summary["detected_languages"], {"hi": 1})
        self.assertEqual(summary["inserted"], 1)


class GenericApiIngestionTests(unittest.TestCase):
    def test_configured_api_sources_are_upserted(self):
        response = {
            "source_url": "https://example.test/api",
            "response_kind": "json",
            "records": [{"id": 1}],
        }
        reader = Mock()
        reader.load.return_value = [response]
        database = Mock()
        database.collection.count_documents.side_effect = [0, 1]
        database.upsert_records.return_value = {
            "inserted": 1,
            "matched": 0,
            "modified": 0,
        }

        summary = ingest_api_urls(
            [response["source_url"]],
            database=database,
            reader=reader,
        )

        database.upsert_records.assert_called_once_with(
            response["source_url"],
            "json",
            [{"id": 1}],
        )
        self.assertEqual(summary["sources_processed"], 1)
        self.assertEqual(summary["records_processed"], 1)
        self.assertEqual(summary["inserted"], 1)


class GenericApiMongoTests(unittest.TestCase):
    def test_upserts_unique_payloads_once_per_source(self):
        database = object.__new__(ApiDocumentsMongo)
        database.collection = Mock()
        database.collection.bulk_write.return_value = SimpleNamespace(
            upserted_count=1,
            matched_count=0,
            modified_count=0,
        )

        result = database.upsert_records(
            "https://example.test/api",
            "json",
            [{"id": 1}, {"id": 1}],
        )

        operations = database.collection.bulk_write.call_args.args[0]
        self.assertEqual(len(operations), 1)
        self.assertEqual(
            operations[0]._filter["source_url"],
            "https://example.test/api",
        )
        self.assertTrue(operations[0]._filter["record_hash"])
        self.assertEqual(result["inserted"], 1)


if __name__ == "__main__":
    unittest.main()
