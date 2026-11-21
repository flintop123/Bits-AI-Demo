import hashlib
import io
import os
import unittest
from email.message import Message
from types import SimpleNamespace
from unittest.mock import Mock, patch

from data_api import create_app
from ingest_any_source import ingest_api_urls, translate_hindi_chunks
from main import create_rag_app
from node.final_answer import FinalAnswerNode
from sync_mongodb_to_milvus import sync_mongodb_to_milvus
from tools.api_extractor.generic_api import BoundedApiReader, MAX_BODY_BYTES, parse_api_response


class FakeResponse(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.headers = Message()
        self.headers["Content-Type"] = "application/json; charset=utf-8"


class IntakeTests(unittest.TestCase):
    def test_api_preview_attaches_exact_body_hash_and_json_path_and_never_writes(self):
        raw = b'{"data":[{"market":"Arwal", "price":1200}]}'
        opener, database = Mock(), Mock()
        opener.open.return_value = FakeResponse(raw)
        result = ingest_api_urls(
            ["https://example.test/data"],
            reader=BoundedApiReader(allowed_hosts=["example.test"], opener=opener),
            database=database,
        )
        self.assertFalse(result["saved"])
        self.assertEqual(result["sources"][0]["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["sources"][0]["sample"][0]["locator"], {"json_path": "$.data[0]"})
        database.upsert_records.assert_not_called()

    def test_unsafe_endpoint_never_opens_and_oversize_body_is_rejected(self):
        opener = Mock()
        reader = BoundedApiReader(allowed_hosts=["example.test", "127.0.0.1"], opener=opener)
        for url in ("http://example.test/data", "https://other.test/data", "https://127.0.0.1/api"):
            with self.assertRaises(ValueError):
                reader.load([url])
        opener.open.assert_not_called()
        opener.open.return_value = FakeResponse(b"x" * (MAX_BODY_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "preview limit"):
            reader.load(["https://example.test/data"])

    def test_ambiguous_html_headings_and_spans_fail_closed(self):
        for headers in ("<th>X</th><th>x</th>", '<th colspan="2">X</th>'):
            with self.assertRaisesRegex(ValueError, "reviewed mapping"):
                parse_api_response(
                    f"<table><tr>{headers}</tr><tr><td>1</td><td>2</td></tr></table>", "text/html",
                )

    def test_derived_translation_does_not_change_source_text_or_hash(self):
        hindi = "अरवल में कृषि"
        source = {"language": "hi", "content": hindi, "content_hash": "evidence-hash"}
        translated = translate_hindi_chunks(
            [source], lambda: SimpleNamespace(translate=lambda _: "Agriculture in Arwal", model_name="fixture"),
        )[0]
        self.assertEqual({key: translated[key] for key in source}, source)
        self.assertEqual(translated["translated_content"], "Agriculture in Arwal")
        self.assertEqual(translated["translation_status"], "machine_translation_unverified")


class CorpusTests(unittest.TestCase):
    def config(self):
        return {"document_ingestion": {"approved_document_sources": ["https://example.test/public.pdf"]}}

    @patch("sync_mongodb_to_milvus.connections.connect")
    @patch("sync_mongodb_to_milvus.MongoClient")
    def test_plan_has_no_network_and_no_database_side_effects(self, mongo, milvus):
        plan = sync_mongodb_to_milvus(self.config(), collection_name="agri_public_v1")
        self.assertEqual(plan["mode"], "plan_only")
        self.assertEqual(plan["mongo_collection"], "agriculture_documents")
        self.assertFalse(plan["saved"])
        mongo.assert_not_called()
        milvus.assert_not_called()

    @patch.dict(os.environ, {"AGRI_MILVUS_URI": "https://example.test", "AGRI_MILVUS_TOKEN": ""})
    @patch("sync_mongodb_to_milvus.connections.connect")
    def test_remote_target_requires_separate_confirmation(self, connect):
        with self.assertRaisesRegex(ValueError, "allow-remote"):
            sync_mongodb_to_milvus(self.config(), collection_name="agri_v2", write=True)
        connect.assert_not_called()

    @patch.dict(os.environ, {"AGRI_MILVUS_URI": "http://127.0.0.1:19530", "AGRI_MILVUS_TOKEN": ""})
    @patch("sync_mongodb_to_milvus._get_or_create_milvus_collection")
    @patch("sync_mongodb_to_milvus.connections")
    def test_existing_corpus_is_never_overwritten(self, _connections, collection):
        existing = Mock()
        collection.return_value = existing, False
        with self.assertRaisesRegex(ValueError, "new collection name"):
            sync_mongodb_to_milvus(
                self.config(), collection_name="agri_current", write=True,
                mongo_client={"bihar_agriculture": Mock()},
            )
        existing.upsert.assert_not_called()
        existing.drop.assert_not_called()


class QATests(unittest.TestCase):
    def test_duplicate_urls_keep_distinct_citation_ids_and_locators(self):
        model = Mock()
        model.invoke.return_value = SimpleNamespace(content="Supported by [3].")
        out = FinalAnswerNode(model).generate_final_answer({
            "question": "What was reported?",
            "retrieved_documents": [
                {"source": "https://example.test/a", "text_content": "A1", "metadata": {"page_number": 1}},
                {"source": "https://example.test/a", "text_content": "A2", "metadata": {"page_number": 2}},
                {"source": "https://example.test/b", "text_content": "B1", "metadata": {"page_number": 3}},
            ],
        })
        self.assertEqual(len(out["source"]), 3)
        self.assertEqual(out["citations"][2]["id"], 3)
        self.assertEqual(out["citations"][2]["page_number"], 3)

    def test_bogus_citations_return_a_localized_abstention(self):
        model = Mock()
        model.invoke.return_value = SimpleNamespace(content="गलत उत्तर [99]")
        out = FinalAnswerNode(model).generate_final_answer({
            "question": "क्या?",
            "retrieved_documents": [{"source": "https://example.test/a", "text_content": "Verified text"}],
        })
        self.assertIn("साक्ष्य नहीं", out["answer"])
        self.assertEqual(out["citations"], [])

    def test_endpoint_bounds_input_and_never_accepts_a_user_thread_id(self):
        rag = Mock()
        rag.runnable.invoke.return_value = {"answer": "Hello"}
        with create_rag_app(rag=rag, access_key="local-fixture-key").test_client() as client:
            url = "/bihar-crop-chatbot/ask"
            self.assertEqual(client.post(url, json={"question": "hello"}).status_code, 401)
            headers = {"Authorization": "Bearer local-fixture-key", "X-Thread-ID": "shared"}
            self.assertEqual(client.post(url, json={"question": "x" * 501}, headers=headers).status_code, 400)
            self.assertEqual(client.post(url, json={"question": "hello"}, headers=headers).status_code, 200)
            token = rag.runnable.invoke.call_args.kwargs["config"]["configurable"]["thread_id"]
            self.assertNotEqual(token, "shared")


class MapIntegrationTests(unittest.TestCase):
    def test_flask_serves_only_the_two_shared_map_assets(self):
        with create_app(Mock(), Mock()).test_client() as client:
            for name in ("market-explorer.js", "market-explorer.css"):
                with client.get(f"/market-explorer/{name}") as response:
                    self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get("/market-explorer/dashboard.js").status_code, 404)
