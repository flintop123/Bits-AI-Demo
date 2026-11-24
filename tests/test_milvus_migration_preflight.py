"""Migration preflight must never read private row fields or contact a provider."""
from collections import defaultdict
from contextlib import redirect_stdout
from io import StringIO
import json
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts import milvus_migration_preflight as preflight
from services.milvus_public_demo import REPORT, SOURCE, TITLE, public_passages


def synthetic_db(documents):
    collections = defaultdict(Mock)
    db = Mock()
    accesses = []

    def get(name):
        accesses.append(name)
        if name == "future_unknown_collection":
            raise AssertionError("Unknown data must never be opened")
        return collections[name]

    db.__getitem__ = Mock(side_effect=get)
    db.list_collection_names.return_value = [*preflight.COLLECTIONS, "extractor_runs", "future_unknown_collection"]
    collections["agriculture_documents"].count_documents.return_value = len(documents) + 3
    collections["agriculture_documents"].find.return_value.limit.return_value = documents
    collections["mandi_prices"].count_documents.side_effect = [40, 30]
    collections["crop_statistics"].count_documents.side_effect = [20, 15]
    collections["mandi_locations"].count_documents.side_effect = [10, 7]
    collections["extractor_runs"].count_documents.return_value = 19
    return db, collections, accesses


class MigrationPreflightTests(TestCase):
    def test_default_uses_reviewed_snapshot_offline_and_never_contacts_cloud(self):
        output = StringIO()
        with (patch("scripts.milvus_migration_preflight.live_inventory",
                    side_effect=AssertionError("Mongo not requested")),
              patch("services.milvus_public_demo._connect", side_effect=AssertionError("Cloud forbidden")),
              redirect_stdout(output)):
            self.assertEqual(preflight.main([]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["mode"], "bundled_snapshot_not_live")
        self.assertEqual(result["records_in_inventoried_collections"], {
            "agriculture_documents": 221, "mandi_prices": 7713,
            "crop_statistics": 4372, "mandi_locations": 42,
        })
        self.assertEqual(result["existing_milvus_pilot"]["unique_matching_passages"], 54)
        self.assertEqual(result["existing_milvus_pilot"]["outside_pilot_scope"], 167)
        self.assertEqual(result["structured_rows_for_separate_review_not_export_approved"], {
            "official_source_label_mandi": 7698, "official_workbook_label_crop": 4297,
            "verified_label_market_coordinates": 42,
        })
        self.assertEqual((result["writes"], result["exported_records"], result["cloud_contacted"]), (0, 0, False))

    def test_internal_counts_only_and_source_label_not_approval(self):
        approved = [
            {"page_number": page, "chunk_index": chunk, "content": text}
            for (page, chunk), text in public_passages().items()
        ]
        approved += [dict(approved[0]), {**approved[1], "content": "DO_NOT_PRINT_PRIVATE_SENTINEL"}]
        db, collections, accesses = synthetic_db(approved)
        result = preflight.inventory_database(db)
        self.assertEqual(result["known_internal_records_count_only_never_export"], 19)
        self.assertEqual(result["other_collections_not_opened"], 1)
        self.assertEqual(accesses.count("extractor_runs"), 1)
        self.assertEqual([method for method, _, _ in collections["extractor_runs"].method_calls],
                         ["count_documents"])
        collections["agriculture_documents"].find.assert_called_once_with(
            {"source_file": REPORT, "source_url": SOURCE, "document_title": TITLE},
            {"_id": 0, "page_number": 1, "chunk_index": 1, "content": 1},
        )
        self.assertEqual(result["existing_milvus_pilot"]["unique_matching_passages"], 54)
        self.assertEqual(result["existing_milvus_pilot"]["duplicate_exact_passages"], 1)
        self.assertEqual(result["existing_milvus_pilot"]["unexpected_passages_with_same_source_identity"], 1)
        self.assertFalse(result["existing_milvus_pilot"]["exact_pilot_corpus_present"])
        self.assertNotIn("DO_NOT_PRINT_PRIVATE_SENTINEL", json.dumps(result))
        self.assertNotIn("future_unknown_collection", json.dumps(result))

    def test_large_same_source_candidates_stop_at_known_bound(self):
        db, _, _ = synthetic_db([{}] * (preflight._REPORT_SCAN_LIMIT + 5))
        result = preflight.inventory_database(db)["existing_milvus_pilot"]
        self.assertTrue(result["scan_truncated"])
        self.assertFalse(result["exact_pilot_corpus_present"])
        self.assertEqual(result["unexpected_passages_with_same_source_identity"], preflight._REPORT_SCAN_LIMIT)

    def test_live_cli_connects_only_to_explicit_loopback_mongo_config(self):
        factory, client = Mock(), Mock()
        factory.return_value.__enter__ = Mock(return_value=client)
        factory.return_value.__exit__ = Mock(return_value=False)
        client.__getitem__ = Mock()
        with (patch("pymongo.MongoClient", factory),
              patch("scripts.milvus_migration_preflight.inventory_database", return_value={}),
              redirect_stdout(StringIO())):
            self.assertEqual(preflight.main(["--live", "--port", "27320"]), 0)
        self.assertEqual(factory.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(factory.call_args.kwargs["port"], 27320)
        self.assertTrue(factory.call_args.kwargs["directConnection"])
        client.__getitem__.assert_called_once_with("bihar_agriculture")
