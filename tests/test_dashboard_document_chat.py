from contextlib import nullcontext
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx
from pymongo.errors import OperationFailure

from data_api import create_app
from services.dashboard_document_chat import DashboardDocumentChat, DocumentChatUnavailable


URL = "/api/v1/viva/document-chat"
HEADERS = {"X-Agri-Dashboard": "1"}
DUMP = Path(__file__).resolve().parents[1] / "db" / "dump" / "agriculture_documents.jsonl"


def pinned_row(filename, page, chunk=0):
    with DUMP.open(encoding="utf-8") as dump:
        return next(record for line in dump if (
            (record := json.loads(line))["source_file"] == filename
            and record["page_number"] == page and record["chunk_index"] == chunk
        ))


SOURCE_EN = "bihar_horticulture_baipp_brochure.pdf"
SOURCE_HI = "apeda_makhana_report_hindi.pdf"
QUERY_HI = "बीएआईपीपी पुस्तिका के अनुसार पीएमएफएमई में खाद्य प्रसंस्करण इकाई के उन्नयन के लिए वित्तीय सहायता कितनी है?"
QUERY_EN = "Where does the APEDA report say makhana is mainly cultivated in Bihar?"
QUOTE_EN = ("Credit-linked capital subsidy @35% of the eligible project cost for expansion/ "
            "technology upgradation with a maximum ceiling of Rs.10 lakh per unit.")
QUOTE_HI = ("यह मुख्य रूप से बिहार के मिथिला क्षेत्र में और पश्चिम बंगाल, असम, "
            "उत्तर प्रदेश और छत्तीसगढ़ के कुछ हिस्सों में उगाया जाता है।")


class ScriptedModel:
    def __init__(self, phrases, summary, quotes):
        self.phrases, self.summary, self.quotes = phrases, summary, quotes
        self.calls = []

    def with_structured_output(self, schema):
        def invoke(messages):
            self.calls.append((schema.__name__, messages))
            if schema.__name__ == "QuestionSuggestions":
                return {"questions": self.phrases}
            return {"summary": self.summary, "evidence": self.quotes}
        return Mock(invoke=invoke)


class DocumentChatTests(TestCase):
    def fixture(self, row, matching, summary, quote, phrases):
        query = Mock()
        query.search_agriculture_documents.side_effect = (
            lambda term, limit: [row] if matching in term else []
        )
        model = ScriptedModel(phrases, summary, [{"passage": 1, "quote": quote}])
        return DashboardDocumentChat(lambda: nullcontext(query), lambda: model), query, model

    @patch("conn.milvusDbConnector.RecZillizVector.connect",
           side_effect=AssertionError("The original cloud vector connector must not be called"))
    def test_hindi_query_retrieves_english_pmfme_and_keeps_english_exact_quote(self, vector):
        sample = pinned_row(SOURCE_EN, 11)
        chat, query, model = self.fixture(
            sample, "capital subsidy", "पात्र परियोजना लागत पर 35% सहायता, अधिकतम ₹10 लाख प्रति इकाई।",
            QUOTE_EN, ["PMFME capital subsidy technology upgradation brochure",
                       "PMFME credit linked support for individual microenterprise",
                       "पीएमएफएमई व्यक्तिगत इकाई सहायता", "खाद्य इकाई प्रौद्योगिकी उन्नयन ब्याज सहायता"],
        )
        qa, react, upload = Mock(), Mock(), Mock()
        client = create_app(Mock(), qa, viva_react=react, viva_upload_store=upload,
                            viva_document_chat=chat).test_client()
        self.assertIn(b"Document Chat", client.get("/").data)
        model.calls.clear()
        got = client.post(URL, json={"question": QUERY_HI, "answer_language": "hi"}, headers=HEADERS)
        self.assertEqual(got.status_code, 200, got.json)
        self.assertEqual(got.headers["Cache-Control"], "no-store")
        self.assertEqual(got.json["document_chat"]["status"], "cited")
        self.assertEqual(got.json["document_chat"]["provider"], "mongodb_keyword")
        self.assertIn("35%", got.json["answer"])
        self.assertIn("₹10 लाख", got.json["answer"])
        self.assertEqual(got.json["records"][0]["content"], QUOTE_EN)
        self.assertEqual(got.json["sources"][0]["source"], sample["source_url"])
        self.assertEqual(got.json["sources"][0]["page_number"], 11)
        self.assertEqual(got.json["sources"][0]["chunk_index"], 0)
        self.assertTrue(any("capital subsidy" in k for k in got.json["document_chat"]["searches"]))
        self.assertIn("two in English and two in Hindi", model.calls[0][1][0].content)
        self.assertIn("untrusted evidence", model.calls[-1][1][0].content)
        self.assertTrue(all("semantic_query" not in c.kwargs for c in query.search_agriculture_documents.call_args_list))
        qa.ask.assert_not_called()
        react.ask.assert_not_called()
        upload.assert_not_called()
        vector.assert_not_called()

    def test_english_query_retrieves_hindi_apeda_and_keeps_hindi_exact_quote(self):
        sample = pinned_row(SOURCE_HI, 11)
        chat, _, _ = self.fixture(
            sample, "मिथिला", "The APEDA report identifies the Mithila region of Bihar.",
            QUOTE_HI, ["APEDA makhana growing regions Bihar", "Makhana crop location in Bihar",
                       "बिहार मखाना मिथिला खेती", "एपीडा मखाना उगाने वाला प्रमुख क्षेत्र"],
        )
        got = chat.ask(QUERY_EN, "en")
        self.assertEqual(got["document_chat"]["status"], "cited")
        self.assertIn("Mithila", got["answer"])
        self.assertEqual(got["records"][0]["content"], QUOTE_HI)
        self.assertEqual(got["sources"][0]["source"], sample["source_url"])

    def test_matches_public_annual_scheme_saved_citation(self):
        sample = pinned_row("bihar_annual_scheme_2022_23.pdf", 14)
        chat, _, _ = self.fixture(
            sample, "organic", "The report says the corridor comprises 13 districts [1].",
            "This corridor comprises 13 districts of Bihar.",
            ["Organic corridor districts", "Bihar organic corridor", "जैविक गलियारा जिले", "जैविक कॉरिडोर बिहार"],
        )
        got = chat.ask("How many districts are in the organic corridor?")
        self.assertEqual(got["document_chat"]["status"], "cited")
        self.assertEqual(got["sources"][0]["page_number"], 14)
        self.assertIn("13 districts", got["answer"])

    def test_suppresses_unverified_numeric_summary_and_refuses_invented_quote(self):
        sample = pinned_row(SOURCE_EN, 11)
        chat, _, model = self.fixture(
            sample, "PMFME".casefold(), "Maximum is ₹99 lakh.", QUOTE_EN,
            ["PMFME subsidy", "PMFME upgrade", "पीएमएफएमई योजना सहायता", "प्रसंस्करण अनुदान"],
        )
        got = chat.ask("What support does PMFME provide?")
        self.assertEqual(got["document_chat"]["status"], "evidence_only")
        self.assertNotIn("99", got["answer"])
        self.assertEqual(got["records"][0]["content"], QUOTE_EN)
        model.summary = "The source is https://example.test/model-invented."
        got = chat.ask("What support does PMFME provide?")
        self.assertEqual(got["document_chat"]["status"], "evidence_only")
        self.assertNotIn("model-invented", got["answer"])
        model.quotes = [{"passage": 1, "quote": "The scheme gives everyone ₹99 lakh."}]
        got = chat.ask("What support does PMFME provide?")
        self.assertEqual(got["document_chat"]["status"], "no_evidence")
        self.assertEqual(got["sources"], [])
        model.quotes = [{"passage": 2, "quote": QUOTE_EN}]
        got = chat.ask("What support does PMFME provide?")
        self.assertEqual(got["document_chat"]["status"], "no_evidence")

    def test_no_evidence_does_not_call_synthesis_and_local_files_are_ignored(self):
        row = {**pinned_row(SOURCE_HI, 11), "source_url": "file:///private.pdf"}
        chat, _, model = self.fixture(
            row, "मिथिला", "unsupported", QUOTE_HI,
            ["APEDA makhana", "makhana crop region", "बिहार मखाना मिथिला", "मखाना खेती प्रमुख क्षेत्र"],
        )
        got = chat.ask(QUERY_EN)
        self.assertEqual(got["document_chat"]["status"], "no_evidence")
        self.assertEqual(got["records"], [])
        self.assertEqual([name for name, _ in model.calls], ["QuestionSuggestions"])

    def test_invalid_request_isolated_from_other_workflows(self):
        qa, react, doc = Mock(), Mock(), Mock()
        qa.ask.return_value = {"answer": "Checked Arwal price"}
        react.ask.return_value = {"answer": "ReAct checked price"}
        doc.ask.side_effect = RuntimeError("never include raw error body")
        client = create_app(Mock(), qa, viva_react=react, viva_document_chat=doc).test_client()
        self.assertEqual(client.post(URL, json={"question": QUERY_EN}).status_code, 403)
        self.assertEqual(client.post(URL, json={"question": QUERY_EN}, headers={**HEADERS, "Origin": "https://example.test"}).status_code, 403)
        self.assertEqual(client.post(URL, json={"question": QUERY_EN, "source_url": "file:///secrets"}, headers=HEADERS).status_code, 400)
        doc.ask.assert_not_called()
        response = client.post(URL, json={"question": QUERY_EN}, headers=HEADERS)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("raw error", response.json["error"])
        self.assertEqual(client.post("/api/v1/ask", json={"question": "What is the potato price in Arwal mandi?"}).status_code, 200)
        self.assertEqual(client.post("/api/v1/viva/react", json={"question": "What is the potato price in Arwal mandi?"}, headers=HEADERS).status_code, 200)

    @patch.dict("os.environ", {"MONGODB_URI": "mongodb://not-local.example:27017/"})
    @patch("pymongo.MongoClient", side_effect=AssertionError("remote MongoDB connection"))
    def test_remote_mongodb_rejected_without_connection(self, client):
        with self.assertRaisesRegex(DocumentChatUnavailable, "loopback MongoDB"):
            DashboardDocumentChat().ask(QUERY_EN)
        client.assert_not_called()

    @patch("agent_config.OLLAMA_URL", "https://not-local.example:11434")
    @patch("httpx.Client", side_effect=AssertionError("remote Ollama connection"))
    def test_remote_ollama_rejected_without_connection(self, http_client):
        with self.assertRaisesRegex(DocumentChatUnavailable, "loopback Ollama"):
            DashboardDocumentChat(lambda: nullcontext(Mock())).ask(QUERY_EN)
        http_client.assert_not_called()

    def test_missing_mongo_text_index_returns_service_unavailable(self):
        query = Mock()
        query.search_agriculture_documents.side_effect = OperationFailure("private internal host")
        model = ScriptedModel(["APEDA report", "Growing area", "मखाना क्षेत्र", "मखाना उत्पादन"], "", [])
        doc = DashboardDocumentChat(lambda: nullcontext(query), lambda: model)
        client = create_app(Mock(), Mock(), viva_document_chat=doc).test_client()
        response = client.post(URL, json={"question": QUERY_EN}, headers=HEADERS)
        self.assertEqual(response.status_code, 503)
        self.assertIn("text index", response.json["error"])
        self.assertNotIn("private internal host", response.json["error"])

    @patch("httpx.Client")
    def test_local_ollama_transport_disables_proxies_and_redirects(self, factory):
        client = factory.return_value.__enter__.return_value
        client.post.side_effect = httpx.ConnectError("unavailable")
        doc = DashboardDocumentChat(lambda: nullcontext(Mock()))
        with self.assertRaisesRegex(DocumentChatUnavailable, "Local Ollama"):
            doc.ask(QUERY_EN)
        factory.assert_called_once_with(timeout=25, trust_env=False, follow_redirects=False)
