import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

from ingest_mandi import count_records, resolve_urls, run_ingestion


class IngestMandiTests(unittest.TestCase):
    def test_resolve_urls_uses_config(self):
        config = {
            "bihar_krishi": {
                "urls": ["https://example.test"]
            }
        }
        self.assertEqual(
            resolve_urls(None, config),
            ["https://example.test"],
        )

    def test_resolve_urls_rejects_missing_configuration(self):
        with self.assertRaisesRegex(ValueError, "No mandi URL"):
            resolve_urls(None, {})

    def test_count_records_counts_all_documents(self):
        documents = [
            SimpleNamespace(
                page_content=json.dumps([{"id": 1}, {"id": 2}])
            ),
            SimpleNamespace(
                page_content=json.dumps([{"id": 3}])
            ),
        ]
        self.assertEqual(count_records(documents), 3)

    def test_each_document_keeps_its_source(self):
        first = SimpleNamespace(
            page_content=json.dumps([{"id": 1}]),
            source="https://source-one.test",
            metadata={},
        )
        second = SimpleNamespace(
            page_content=json.dumps([{"id": 2}]),
            source="https://source-two.test",
            metadata={},
        )

        database = Mock()
        database.collection.count_documents.side_effect = [10, 12]
        database.write_mandi_records.side_effect = [1, 1]

        reader = Mock()
        reader.load_bihar_krishi_mandi_pages.return_value = [
            first,
            second,
        ]

        summary = run_ingestion(
            [first.source, second.source],
            database=database,
            reader=reader,
        )

        database.write_mandi_records.assert_has_calls([
            call([first], source_url=first.source),
            call([second], source_url=second.source),
        ])

        self.assertEqual(summary["processed"], 2)
        self.assertEqual(summary["inserted"], 2)
        self.assertEqual(summary["count_before"], 10)
        self.assertEqual(summary["count_after"], 12)


if __name__ == "__main__":
    unittest.main()
