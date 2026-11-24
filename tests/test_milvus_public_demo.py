"""No tests connect to Zilliz, Ollama, or MongoDB."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch

from langchain_core.messages import HumanMessage, SystemMessage

from data_api import create_app
from milvus_public_demo import main
from services.milvus_public_demo import (
    DemoError, PublicMilvusDemo, QUESTION, REPORT, SOURCE, Target, _GenerationFailure, _LoopbackChat,
    public_passages, seed,
)

ENDPOINT = "https://review.vectordb.zillizcloud.com"
COLLECTION = "agriagent_demo_19928811adde"
TOKEN = "SECRET_FOR_TEST_NOT_A_REAL_KEY"
HEADERS = {"X-Agri-Dashboard": "1"}
ROUTE = "/api/v1/viva/milvus-demo"


def hit(text, *, source=SOURCE, metadata=None, rank=0.83):
    return {"id": "never-surface-this-id", "distance": rank, "entity": {
        "source": source, "text_content": text, "metadata": metadata or {"page_number": 14, "chunk_index": 0},
    }}


class MilvusPublicDemoTests(TestCase):
    def setUp(self):
        self.rows = public_passages()
        self.embedder = Mock()
        self.embedder.embed_query.return_value = [0.03125] * 1024
        self.embedder.embed_texts.side_effect = lambda texts: [[0.03125] * 1024 for _ in texts]
        self.client = Mock()
        self.client.has_collection.return_value = True
        self.client.search.return_value = [[hit(self.rows[14, 0])]]
        self.connect = Mock(return_value=self.client)
        self.model = Mock()
        self.model.invoke.return_value.content = "The report says the corridor comprises 13 districts of Bihar. [1]"
        self.model_factory = Mock(return_value=self.model)
        self.docs = Mock()
        self.docs.ask.return_value = {"answer": "Separate Mongo chat"}
        self.qa = Mock()
        self.query = Mock()

    def make_demo(self, *, shared=False):
        target = Target(ENDPOINT, "approved_team_reports" if shared else COLLECTION, shared)
        return PublicMilvusDemo(target, TOKEN, rows=self.rows, embedder=self.embedder,
                                client_factory=self.connect, model_factory=self.model_factory)

    def make_app(self, demo=None):
        return create_app(self.query, self.qa, viva_document_chat=self.docs,
                          viva_milvus_chat=demo).test_client()

    def request(self, app, question=QUESTION, headers=HEADERS, **extra):
        return app.post(ROUTE, headers=headers, json={"question": question, "answer_language": "en"}, **extra)

    def test_default_preview_does_not_call_credentials_or_providers(self):
        out = StringIO()
        ask_for_token = Mock(side_effect=AssertionError("preview token input"))
        with (patch("services.milvus_public_demo._connect", side_effect=AssertionError("cloud")),
              redirect_stdout(out)):
            self.assertEqual(main([], token_reader=ask_for_token), 0)
        self.assertIn("54 reviewed public passages", out.getvalue())
        self.assertIn("no service contacted", out.getvalue())
        ask_for_token.assert_not_called()
        self.assertEqual(len(self.rows), 54)

    def test_source_file_match_without_reviewed_bytes_is_not_enough(self):
        from services import milvus_public_demo as package
        with tempfile.TemporaryDirectory() as temp:
            records = [json.loads(line) for line in package.DUMP.read_text(encoding="utf-8").splitlines()]
            row = next(row for row in records if row.get("source_file") == REPORT)
            row["content"] += " Something private."
            mutated = Path(temp) / "modified.jsonl"
            mutated.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
            with patch.object(package, "DUMP", mutated), self.assertRaisesRegex(DemoError, "differ"):
                public_passages()

    def test_legacy_gcp_serving_endpoint_is_narrowly_allowed(self):
        prefix = "in03-0123456789abcde"
        valid = [
            f"https://{prefix}.serverless.gcp-us-west1.cloud.zilliz.com",
            f"https://{prefix}.gcp-europe-west4.cloud.zilliz.com:443/",
            f"https://{prefix}.serverless.gcp-us-west1.vectordb.zillizcloud.com",
        ]
        for endpoint in valid:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(Target(endpoint, COLLECTION).endpoint, endpoint)
        for endpoint in (
            valid[0] + ".example.org", valid[0] + "@example.org",
            valid[0] + "/v2/vectordb", valid[0] + "?secret", valid[0] + "?", valid[0] + "#",
            valid[0].replace("https:", "http:"), valid[0].replace("in03-", "in03-\t"),
            valid[0].replace("https://", "https://@"),
            valid[0].replace("https://", "https://name:password@"),
            valid[0].replace("cloud.zilliz.com", "cloud-zilliz.com"),
            valid[0].replace(prefix, "other"), valid[0].replace("gcp-", "aws-"),
            "https://api.cloud.zilliz.com", "https://cloud.zilliz.com",
            valid[0] + ":8080", valid[0] + "\\other",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(DemoError, "approved Zilliz"):
                Target(endpoint, COLLECTION)

    def test_write_requires_explicit_new_collection_approval(self):
        prompt = Mock(side_effect=AssertionError("credential prompt must not run"))
        with redirect_stderr(StringIO()):
            for args in (["seed", "--endpoint", ENDPOINT, "--collection", COLLECTION],
                         ["seed", "--endpoint", ENDPOINT, "--collection", "shared",
                          "--shared-read-only", "--approve-public-upload"],
                         ["serve", "--endpoint", "https://example.org", "--collection", COLLECTION]):
                self.assertEqual(main(args, token_reader=prompt), 1)
        prompt.assert_not_called()

    def test_seed_sends_exact_public_fields_and_refuses_existing_target(self):
        target = Target(ENDPOINT, COLLECTION)
        with self.assertRaisesRegex(DemoError, "exists"):
            seed(target, TOKEN, self.rows, embedder=self.embedder, client_factory=self.connect)
        self.client.insert.assert_not_called()
        self.client.create_collection.assert_not_called()
        self.client.has_collection.return_value = False
        self.client.insert.return_value = {"insert_count": 54}
        self.assertEqual(seed(target, TOKEN, self.rows, embedder=self.embedder, client_factory=self.connect), 54)
        self.client.create_collection.assert_called_once()
        name, payload = self.client.insert.call_args.args
        self.assertEqual(name, COLLECTION)
        self.assertEqual(len(payload), 54)
        for record in payload:
            self.assertEqual(set(record), {"pk", "embedding", "source", "text_content", "metadata"})
            self.assertEqual(record["source"], SOURCE)
            self.assertEqual(set(record["metadata"]), {"page_number", "chunk_index"})
            page, chunk = record["metadata"]["page_number"], record["metadata"]["chunk_index"]
            self.assertEqual(record["text_content"], self.rows[page, chunk])

    def test_ui_opt_in_and_same_origin_then_real_nodes_use_only_the_validated_hits(self):
        default = self.make_app()
        self.assertNotIn(b"Milvus Vector RAG", default.get("/").data)
        self.assertEqual(self.request(default).status_code, 503)
        enabled = self.make_app(self.make_demo())
        self.assertIn(b"Milvus Vector RAG", enabled.get("/").data)
        self.assertEqual(self.request(enabled, headers={}).status_code, 403)
        self.assertEqual(self.request(enabled, headers={**HEADERS, "Origin": "http://foreign.test"}).status_code, 403)
        self.assertEqual(self.request(enabled, question="Memo: private user input").status_code, 400)
        self.connect.assert_not_called()
        extra = hit(self.rows[14, 0] + "A private suffix.")
        self.client.search.return_value[0].insert(0, extra)
        response = self.request(enabled)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertIn("13 districts", response.json["answer"])
        self.assertEqual(response.json["intent"], "milvus_vector_rag")
        self.assertEqual(response.json["retrieval"]["mode"], "milvus_dense_cosine")
        self.assertEqual(response.json["document_chat"]["status"], "cited")
        self.assertEqual([r["page_number"] for r in response.json["records"]], [14])
        self.assertEqual(response.json["records"][0]["content"], self.rows[14, 0])
        search = self.client.search.call_args
        self.assertEqual(search.args, (COLLECTION,))
        self.assertEqual(search.kwargs["anns_field"], "embedding")
        self.assertIn(SOURCE, search.kwargs["filter"])
        self.assertNotIn("private suffix", self.model.invoke.call_args.args[0][-1].content)
        self.assertNotIn(TOKEN, response.get_data(as_text=True))
        self.docs.ask.assert_not_called()
        self.qa.ask.assert_not_called()
        for method in ("insert", "upsert", "create_collection", "drop_collection"):
            getattr(self.client, method).assert_not_called()

    def test_shared_read_only_filters_scope_and_removes_mongo_metadata(self):
        source_row = {
            "source_file": REPORT, "source_url": SOURCE, "page_number": 14, "chunk_index": 0,
            "content": self.rows[14, 0], "sensitive_mongo_id": "keep-out-of-ai-and-browser",
        }
        self.client.search.return_value = [[hit(json.dumps(source_row))]]
        reply = self.make_demo(shared=True).ask(QUESTION, "en")
        self.assertEqual(reply["document_chat"]["status"], "cited")
        self.assertEqual(self.client.search.call_args.args, ("approved_team_reports",))
        kwargs = self.client.search.call_args.kwargs
        self.assertIn('metadata["mongo_collection"] == "agriculture_documents"', kwargs["filter"])
        self.assertNotIn("metadata", kwargs["output_fields"])
        self.assertNotIn("keep-out-of-ai-and-browser", self.model.invoke.call_args.args[0][-1].content)
        self.assertNotIn("keep-out-of-ai-and-browser", json.dumps(reply))
        self.client.load_collection.assert_not_called()
        self.client.insert.assert_not_called()

    def test_real_local_model_adapter_does_not_use_proxy_or_redirects(self):
        conn = Mock()
        conn.__enter__ = Mock(return_value=conn)
        conn.__exit__ = Mock(return_value=False)
        conn.post.return_value.json.return_value = {"message": {"content": "Answer [1]"}}
        with patch("httpx.Client", return_value=conn) as client:
            output = _LoopbackChat().invoke([SystemMessage(content="Policy"), HumanMessage(content="Evidence")])
        self.assertEqual(output, "Answer [1]")
        self.assertEqual(conn.post.call_args.args, ("http://127.0.0.1:11434/api/chat",))
        self.assertEqual(conn.post.call_args.kwargs["json"]["messages"], [
            {"role": "system", "content": "Policy"}, {"role": "user", "content": "Evidence"},
        ])
        self.assertFalse(client.call_args.kwargs["trust_env"])
        self.assertFalse(client.call_args.kwargs["follow_redirects"])

    def test_generation_uses_small_exact_returned_passage_and_stable_citation(self):
        self.client.search.return_value = [[
            hit(self.rows[11, 0], metadata={"page_number": 11, "chunk_index": 0}, rank=.94),
            hit(self.rows[14, 2], metadata={"page_number": 14, "chunk_index": 2}, rank=.87),
            hit(self.rows[14, 0], rank=.82),
        ]]
        exact = (
            "An organic corridor is established along both banks of river Ganga. "
            "This corridor comprises 13 districts of Bihar."
        )
        self.model.invoke.return_value.content = exact + " [1]"
        result = self.make_demo().ask(QUESTION, "en")
        self.assertEqual(result["answer"], exact + " [1]")
        self.assertEqual(result["document_chat"]["generation"], "accepted")
        messages = self.model.invoke.call_args.args[0]
        self.assertIn("End with the citation [1]", messages[0].content)
        self.assertIn(exact, messages[-1].content)
        self.assertNotIn("188 FPOs", messages[-1].content)
        self.assertNotIn("[2]", messages[-1].content)
        self.assertEqual(result["records"][0]["page_number"], 14)
        self.assertEqual(result["records"][0]["chunk_index"], 0)
        self.assertEqual(result["records"][0]["cosine_score"], .82)
        self.assertEqual(len(result["records"]), 3)

    def test_summary_diagnostics_do_not_reveal_rejected_output_or_fall_back(self):
        app = self.make_app(self.make_demo())
        for content, reason in (
            ("The original numbers are here but I forgot the source.", "missing_citation"),
            ("The corridor comprises 13 districts. [2]", "unknown_citation"),
            ("The corridor comprises 99 districts. [1]", "unsupported_number"),
            ("The corridor covers 13 districts. [1]", "unsupported_amount_unit"),
        ):
            with self.subTest(reason=reason):
                self.model.invoke.return_value.content = content
                response = self.request(app)
                self.assertEqual(response.json["document_chat"]["generation"], reason)
                self.assertEqual(response.json["document_chat"]["status"], "evidence_only")
                self.assertNotIn(content, response.get_data(as_text=True))
                self.assertEqual(response.json["records"][0]["content"], self.rows[14, 0])
        self.model.invoke.side_effect = _GenerationFailure("ollama_timeout")
        reply = self.request(app)
        self.assertEqual(reply.json["document_chat"]["generation"], "ollama_timeout")
        self.docs.ask.assert_not_called()

    def test_no_local_passage_substitution_when_real_vector_hits_are_off_topic(self):
        self.client.search.return_value = [[
            hit(self.rows[11, 0], metadata={"page_number": 11, "chunk_index": 0})
        ]]
        result = self.make_demo().ask(QUESTION, "en")
        self.assertEqual(result["document_chat"]["generation"], "topic_not_retrieved")
        self.assertEqual(result["document_chat"]["status"], "evidence_only")
        self.assertEqual([row["page_number"] for row in result["records"]], [11])
        self.model_factory.assert_not_called()

    def test_no_fallback_when_milvus_fails_or_returns_unapproved_rows(self):
        app = self.make_app(self.make_demo())
        self.client.search.side_effect = RuntimeError(TOKEN)
        failed = self.request(app)
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn(TOKEN, failed.get_data(as_text=True))
        self.client.search.side_effect = None
        self.client.search.return_value = [[hit("Not the verified source text")]]
        empty = self.request(app)
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json["records"], [])
        self.assertEqual(empty.json["document_chat"]["status"], "no_evidence")
        self.docs.ask.assert_not_called()
        self.qa.ask.assert_not_called()
        self.model_factory.assert_not_called()
