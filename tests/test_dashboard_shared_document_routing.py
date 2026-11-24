"""The three local dashboard routes must not synthesize competing report answers."""

from contextlib import nullcontext
from threading import Event, Thread, current_thread
from unittest import TestCase
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage

from data_api import create_app
from services.agriculture_qa_service import AgricultureQAService
from services.dashboard_document_chat import DashboardDocumentChat, DocumentChatUnavailable
from services.viva_dashboard import ReactDashboard
from test_dashboard_document_chat import (
    HEADERS, QUERY_HI, QUOTE_EN, SOURCE_EN, pinned_row,
)
from test_viva_dashboard import ScriptedModel as ReactModel


PREFIX = "/api/v1/viva"
DOC_CASES = (
    QUERY_HI,
    "What financial assistance is available under PMFME for upgrading an individual food processing unit?",
    "पीएमएफएमई के तहत खाद्य प्रसंस्करण इकाई के लिए सब्सिडी कितनी है?",
    "According to the final estimate report, what was rice yield in Bihar?",
)
PRICE_EN = "What is the potato price in Arwal mandi?"
PRICE_HI = "अरवल मंडी में आलू का भाव क्या है?"
CROP = "What was the rice yield in Bihar in 2024-25?"


def make_app(query, qa, document, *, tool=True, calls=1):
    responses = [AIMessage(content="", tool_calls=[{
        "name": "ask_agriculture_question", "args": {}, "id": f"call-{i}",
    } for i in range(calls)])] if tool else [AIMessage(content="This unverified answer must not appear.")]
    # Preserve the production default wiring and run the real bounded ReAct
    # graph; substitute only the model that chooses whether to call the tool.
    with patch("viva_api.ReactDashboard", side_effect=lambda routed_qa: ReactDashboard(
        routed_qa, llm=ReactModel(responses=responses),
    )):
        return create_app(query, qa, viva_document_chat=document)


def ask(app, route, question=QUERY_HI, language="hi", **options):
    kwargs = {"headers": HEADERS, **options}
    return app.test_client().post(PREFIX + route, json={
        "question": question, "answer_language": language,
    }, **kwargs)


class DashboardSharedDocumentTests(TestCase):
    def setUp(self):
        self.query = Mock()
        self.query.list_values.return_value = {"mandi_crops": ["आलू"], "markets": ["अरवल"]}
        self.planner = Mock()
        self.planner.model = "scripted-test-model"
        self.qa = AgricultureQAService(self.query, llm=self.planner)

    def test_three_modes_share_published_hindi_answer_and_actual_react_trace(self):
        corpus_row = pinned_row(SOURCE_EN, 11)
        retrieve = Mock()
        retrieve.search_agriculture_documents.side_effect = (
            lambda terms, limit: [corpus_row] if "pmfme" in terms.lower() else []
        )
        no_model = Mock(side_effect=AssertionError("Typed answer must not load the chat model"))
        chat = DashboardDocumentChat(lambda: nullcontext(retrieve), no_model)
        app = make_app(self.query, self.qa, chat)
        direct, react, explicit = [ask(app, route) for route in ("/ask", "/react", "/document-chat")]
        for response in (direct, react, explicit):
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json["document_chat"]["status"], "source_derived")
            self.assertEqual(response.json["document_chat"]["answer_method"], "typed_source_clause")
            self.assertIn("पात्र परियोजना लागत का 35%", response.json["answer"])
            self.assertIn("अधिकतम ₹10 लाख प्रति इकाई", response.json["answer"])
            self.assertIn(QUOTE_EN, response.json["records"][0]["content"])
            self.assertEqual((response.json["sources"][0]["page_number"],
                              response.json["sources"][0]["chunk_index"]), (11, 0))
        self.assertEqual(direct.json, explicit.json)
        self.assertEqual({k: v for k, v in react.json.items() if k != "react"}, explicit.json)
        self.assertTrue(react.json["react"]["tool_called"])
        self.assertEqual(react.json["react"]["tool"], "ask_agriculture_question")
        self.planner.chat_json.assert_not_called()
        no_model.assert_not_called()
        self.query.search_agriculture_documents.assert_not_called()

    def test_explicit_bilingual_document_prompts_cannot_be_misrouted_by_planner(self):
        self.planner.chat_json.return_value = {"intent": "mandi_price"}
        doc = Mock()
        doc.ask.return_value = {"answer": "Original evidence", "document_chat": {"status": "evidence_only"}}
        app = make_app(self.query, self.qa, doc)
        for question in DOC_CASES:
            for route in ("/ask", "/react"):
                with self.subTest(question=question, route=route):
                    response = ask(app, route, question, "auto")
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertEqual(response.json["document_chat"]["status"], "evidence_only")
                    doc.ask.assert_called_with(question, "auto")
        self.planner.chat_json.assert_not_called()
        self.query.list_values.assert_not_called()
        self.query.find_mandi_prices.assert_not_called()
        self.query.search_agriculture_documents.assert_not_called()

    def test_model_document_plan_uses_chat_but_legacy_api_keeps_existing_contract(self):
        doc = Mock()
        doc.ask.return_value = {
            "answer": "No verified excerpts were found.", "document_chat": {"status": "no_evidence"},
        }
        self.planner.chat_json.return_value = {"intent": "document_search", "search_terms": "monsoon strategy"}
        self.query.search_agriculture_documents.return_value = []
        question = "How is monsoon strategy presented?"
        app = make_app(self.query, self.qa, doc)
        for route in ("/ask", "/react"):
            response = ask(app, route, question, "en")
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json["document_chat"]["status"], "no_evidence")
        self.query.search_agriculture_documents.assert_not_called()
        legacy = app.test_client().post("/api/v1/ask", json={"question": question})
        self.assertEqual(legacy.status_code, 200, legacy.json)
        self.assertEqual(legacy.json["intent"], "document_search")
        self.assertNotIn("document_chat", legacy.json)
        self.query.search_agriculture_documents.assert_called_once()
        self.assertEqual(doc.ask.call_count, 2)

    def test_exact_bilingual_prices_and_structured_crop_statistics_stay_on_legacy_data_path(self):
        doc = Mock()
        self.query.find_mandi_prices.return_value = [{
            "date": "2026-10-23", "crop": "आलू", "market": "अरवल", "district": "ARWAL",
            "variety": "Desi", "modal_price": 1400, "unit": "Quintal",
        }]
        self.query.find_crop_statistics.return_value = []
        self.planner.chat_json.return_value = {
            "intent": "crop_statistics", "crop": "Rice", "year": "2024-25", "metric": "yield",
        }
        app = make_app(self.query, self.qa, doc)
        for route in ("/ask", "/react"):
            for question in (PRICE_EN, PRICE_HI):
                with self.subTest(route=route, question=question):
                    response = ask(app, route, question, "auto")
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertEqual(response.json["planning_method"], "exact_catalog_lookup")
                    self.assertEqual(response.json["filters"]["market"], "अरवल")
                    self.assertEqual(response.json["records"][0]["modal_price"], 1400)
        self.planner.chat_json.assert_not_called()
        for route in ("/ask", "/react"):
            response = ask(app, route, CROP, "en")
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json["intent"], "crop_statistics")
            self.assertEqual(response.json["metric"], "yield")
        doc.ask.assert_not_called()
        self.assertEqual(self.query.find_crop_statistics.call_count, 2)

    def test_requires_same_origin_and_react_never_returns_a_model_guess(self):
        doc = Mock()
        app = make_app(self.query, self.qa, doc, tool=False)
        self.assertEqual(ask(app, "/ask", headers={}).status_code, 403)
        self.assertEqual(ask(app, "/ask", headers={**HEADERS, "Origin": "https://external.example"}).status_code, 403)
        self.assertEqual(ask(app, "/ask", environ_overrides={"REMOTE_ADDR": "192.0.2.1"}).status_code, 403)
        response = ask(app, "/react")
        self.assertEqual(response.status_code, 422, response.json)
        self.assertNotIn("unverified answer", response.json["error"])
        self.assertEqual(ask(app, "/react", "load mandi data via API").status_code, 400)
        doc.ask.assert_not_called()

    def test_all_routes_surface_document_unavailable_and_release_the_shared_slot(self):
        doc = Mock()
        app = make_app(self.query, self.qa, doc)
        for route in ("/ask", "/react", "/document-chat"):
            with self.subTest(route=route):
                doc.ask.side_effect = DocumentChatUnavailable("Check local Ollama.")
                failed = ask(app, route)
                self.assertEqual(failed.status_code, 503, failed.json)
                self.assertEqual(failed.json, {"error": "Check local Ollama."})
                doc.ask.side_effect = None
                doc.ask.return_value = {"answer": "No verified evidence.", "document_chat": {"status": "no_evidence"}}
                self.assertEqual(ask(app, route).status_code, 200)
        doc.ask.side_effect = RuntimeError("do not show this internal message")
        failed = ask(app, "/react")
        self.assertEqual(failed.status_code, 503, failed.json)
        self.assertNotIn("internal message", failed.json["error"])
        self.query.search_agriculture_documents.assert_not_called()

    def test_react_duplicate_tool_calls_run_one_grounded_lookup_per_request(self):
        doc = Mock()
        doc.ask.return_value = {"answer": "Original evidence", "document_chat": {"status": "evidence_only"}}
        app = make_app(self.query, self.qa, doc, calls=2)
        got = ask(app, "/react")
        self.assertEqual(got.status_code, 200, got.json)
        self.assertTrue(got.json["react"]["tool_called"])
        doc.ask.assert_called_once_with(QUERY_HI, "hi")

        doc.ask.reset_mock(side_effect=True)
        doc.ask.side_effect = DocumentChatUnavailable("Check local Ollama.")
        failed = ask(app, "/react")
        self.assertEqual(failed.status_code, 503, failed.json)
        self.assertEqual(failed.json, {"error": "Check local Ollama."})
        doc.ask.assert_called_once_with(QUERY_HI, "hi")

    def test_active_direct_document_request_blocks_explicit_and_react_chat_not_legacy_fallback(self):
        started, release = Event(), Event()
        doc = Mock()
        expected = {"answer": "Original evidence", "document_chat": {"status": "evidence_only"}}

        def hold(*_args):
            # The held request must outlive the busy checks even when Windows
            # starts the ReAct graph slowly. Only the test releases this event.
            # A broken semaphore must fail, not block the competing request.
            if current_thread() is not first:
                raise AssertionError("A competing request reached the Document Chat backend")
            started.set()
            release.wait()
            return expected

        doc.ask.side_effect = hold
        app = make_app(self.query, self.qa, doc)
        responses = []
        first = Thread(target=lambda: responses.append(ask(app, "/ask")), daemon=True)
        first.start()
        try:
            self.assertTrue(started.wait(30), "The first request did not reach Document Chat")
            for route in ("/ask", "/document-chat", "/react"):
                with self.subTest(route=route):
                    busy = ask(app, route)
                    self.assertEqual(busy.status_code, 429, busy.json)
                    self.assertIn("busy", busy.json["error"].lower())
            doc.ask.assert_called_once()
            self.query.search_agriculture_documents.assert_not_called()
        finally:
            release.set()
            first.join(30)
        self.assertFalse(first.is_alive(), "The first request did not finish after release")
        self.assertEqual([response.status_code for response in responses], [200])
        doc.ask.side_effect = None
        doc.ask.return_value = expected
        self.assertEqual(ask(app, "/react").status_code, 200)
