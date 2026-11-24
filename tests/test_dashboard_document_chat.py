from contextlib import nullcontext
import json
from pathlib import Path
import re
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx
from pymongo.errors import OperationFailure

from data_api import create_app
from services.dashboard_document_chat import (
    DashboardDocumentChat, DocumentChatUnavailable, MongoDocumentRetriever,
    _GroundedAnswer, _LocalOllama, _RenderedSummary, _sentence_spans,
)


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
    def __init__(self, phrases, summary, target_quote=None):
        self.phrases, self.summary, self.target_quote = phrases, summary, target_quote
        self.evidence = None
        self.rendered_summary = ""
        self.render_error = None
        self.calls = []

    def with_structured_output(self, schema):
        def invoke(messages):
            self.calls.append((schema.__name__, messages))
            if schema.__name__ == "QuestionSuggestions":
                return {"questions": self.phrases}
            if schema.__name__ == "_RenderedSummary":
                if self.render_error:
                    raise self.render_error
                return {"summary": self.rendered_summary}
            evidence = self.evidence
            if evidence is None:
                evidence = [
                    int(match[1]) for match in re.finditer(
                        r"(?m)^\[([0-9]+)\] [^\n]+\n((?s:.*?))(?=\n\n\[[0-9]+\] |\Z)",
                        messages[-1].content,
                    ) if self.target_quote and self.target_quote in match[2]
                ][:1]
            return {"summary": self.summary, "evidence": evidence}
        return Mock(invoke=invoke)


class DocumentChatTests(TestCase):
    def fixture(self, row, matching, summary, quote, phrases):
        query = Mock()
        query.search_agriculture_documents.side_effect = (
            lambda term, limit: [row] if matching in term else []
        )
        model = ScriptedModel(phrases, summary, quote)
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
        self.assertIn(QUOTE_EN, got.json["records"][0]["content"])
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
        self.assertIn(QUOTE_HI, got["records"][0]["content"])
        self.assertEqual(got["sources"][0]["source"], sample["source_url"])

    def test_matches_public_annual_scheme_saved_citation(self):
        sample = pinned_row("bihar_annual_scheme_2022_23.pdf", 14)
        chat, _, _ = self.fixture(
            sample, "organic", "The report says the corridor comprises 13 districts.",
            "This corridor comprises 13 districts of Bihar.",
            ["Organic corridor districts", "Bihar organic corridor", "जैविक गलियारा जिले", "जैविक कॉरिडोर बिहार"],
        )
        got = chat.ask("How many districts are in the organic corridor?")
        self.assertEqual(got["document_chat"]["status"], "cited")
        self.assertEqual(got["sources"][0]["page_number"], 14)
        self.assertIn("13 districts", got["answer"])

    def test_suppresses_unverified_numeric_summary_and_refuses_unknown_id(self):
        sample = pinned_row(SOURCE_EN, 11)
        chat, _, model = self.fixture(
            sample, "PMFME".casefold(), "Maximum is ₹99 lakh.", QUOTE_EN,
            ["PMFME subsidy", "PMFME upgrade", "पीएमएफएमई योजना सहायता", "प्रसंस्करण अनुदान"],
        )
        got = chat.ask("What support does PMFME provide?")
        self.assertEqual(got["document_chat"]["status"], "evidence_only")
        self.assertNotIn("99", got["answer"])
        self.assertIn(QUOTE_EN, got["records"][0]["content"])
        model.summary = "The source is https://example.test/model-invented."
        got = chat.ask("What support does PMFME provide?")
        self.assertEqual(got["document_chat"]["status"], "evidence_only")
        self.assertNotIn("model-invented", got["answer"])
        accepted_id = got["sources"][0]["citation_id"]
        model.evidence = [accepted_id, 999]
        got = chat.ask("What support does PMFME provide?")
        self.assertEqual(got["document_chat"]["status"], "no_evidence")
        self.assertEqual(got["sources"], [])
        model.evidence = []
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
        factory.assert_called_once_with(
            timeout=httpx.Timeout(90, connect=4, write=10, pool=4),
            trust_env=False, follow_redirects=False,
        )

    @patch("services.dashboard_document_chat.monotonic", side_effect=[0, 0, 95])
    @patch("httpx.Client")
    def test_two_model_calls_share_time_budget_without_retry(self, factory, clock):
        client = factory.return_value.__enter__.return_value
        client.post.return_value = httpx.Response(
            200, request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={"message": {"content": '{"summary":"","evidence":[]}'}},
        )
        run = _LocalOllama("http://127.0.0.1:11434", "test").with_structured_output(_GroundedAnswer)
        self.assertEqual(run.invoke([]).evidence, [])
        self.assertEqual(run.invoke([]).evidence, [])
        self.assertEqual([call.kwargs["timeout"].read for call in factory.call_args_list], [90, 55])
        self.assertEqual([call.kwargs["timeout"].connect for call in factory.call_args_list], [4, 4])
        self.assertEqual(client.post.call_count, 2)

    @patch("services.dashboard_document_chat.monotonic", side_effect=[0, 151])
    @patch("httpx.Client")
    def test_expired_shared_budget_stops_before_connection(self, factory, clock):
        run = _LocalOllama("http://127.0.0.1:11434", "test").with_structured_output(_GroundedAnswer)
        with self.assertRaisesRegex(DocumentChatUnavailable, "time limit"):
            run.invoke([])
        factory.assert_not_called()

    @patch("httpx.Client")
    def test_reports_safe_distinct_timeout_http_envelope_and_json_failures(self, factory):
        client = factory.return_value.__enter__.return_value
        request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
        cases = (
            (httpx.ReadTimeout("private upstream details"), "timed out during answer synthesis", "read timeout"),
            (httpx.ConnectTimeout("private upstream details"), "connection timed out", "connection or write timeout"),
            (httpx.Response(500, request=request, text="private upstream details"), "HTTP 500", "Ollama HTTP 500"),
            (httpx.Response(200, request=request, text="private upstream details"), "invalid response", "malformed Ollama response"),
            (httpx.Response(200, request=request, json={"message": {"content": "private upstream details"}}),
             "invalid structured JSON", "invalid structured JSON"),
        )
        for reply, error, log in cases:
            with self.subTest(error=error):
                client.reset_mock()
                client.post.side_effect = None
                if isinstance(reply, Exception):
                    client.post.side_effect = reply
                else:
                    client.post.return_value = reply
                run = _LocalOllama("http://127.0.0.1:11434", "test").with_structured_output(_GroundedAnswer)
                with self.assertLogs("services.dashboard_document_chat", level="WARNING") as logs:
                    with self.assertRaisesRegex(DocumentChatUnavailable, error) as caught:
                        run.invoke([])
                self.assertIn(log, logs.output[0])
                self.assertNotIn("private upstream details", logs.output[0])
                self.assertNotIn("private upstream details", str(caught.exception))
                self.assertEqual(client.post.call_count, 1)

    def test_named_program_probe_and_ranking_rescue_real_pmfme_from_noisy_brochure(self):
        correct = pinned_row(SOURCE_EN, 11, 0)
        other_pmfme = [pinned_row(SOURCE_EN, 2, 1), pinned_row(SOURCE_EN, 12, 2)]
        # Same BAIPP brochure, adjacent horticulture programs with subsidy
        # terms and even the same percentage as PMFME; not the queried scheme.
        distracting = [pinned_row(SOURCE_EN, page, chunk) for page, chunk in (
            (16, 0), (16, 1), (8, 0), (8, 1), (9, 0), (9, 1), (17, 0),
        )]
        suggestions = ["BAIPP subsidy coverage for food processors", "Assistance for small processing units",
                       "उद्यमों को वित्तीय सहायता कितनी है", "खाद्य उद्योग अनुदान प्रतिशत"]
        query = Mock()
        query.search_agriculture_documents.side_effect = (
            lambda term, limit: [*other_pmfme, correct][:limit] if term == "pmfme"
            else [*distracting, *other_pmfme, correct][:limit]
        )
        state = {"question": QUERY_HI, "subQuestions": suggestions}
        retriever = MongoDocumentRetriever(query)
        result = retriever.retrieve_documents(state)["retrieved_documents"]
        self.assertEqual(retriever.searches[:2], ["baipp", "pmfme"])
        self.assertLessEqual(len(retriever.searches), 7)
        self.assertEqual((result[0]["metadata"]["page_number"], result[0]["metadata"]["chunk_index"]), (11, 0))
        self.assertTrue(all(row["metadata"]["page_number"] != 16 for row in result))
        self.assertTrue(all(call.kwargs == {"limit": 12}
                            for call in query.search_agriculture_documents.call_args_list))
        model = ScriptedModel(suggestions, "परियोजना लागत पर 35% और अधिकतम ₹10 लाख प्रति इकाई।",
                              QUOTE_EN)
        chat = DashboardDocumentChat(lambda: nullcontext(query), lambda: model)
        answer = chat.ask(QUERY_HI, "hi")
        self.assertEqual(answer["document_chat"]["status"], "cited")
        self.assertIn(QUOTE_EN, answer["records"][0]["content"])
        self.assertEqual(answer["sources"][0]["page_number"], 11)

    def test_named_program_never_uses_nearby_wrong_program_when_requested_evidence_absent(self):
        wrong_program = [pinned_row(SOURCE_EN, 16, 0), pinned_row(SOURCE_EN, 16, 1)]
        query = Mock()
        query.search_agriculture_documents.return_value = wrong_program
        model = ScriptedModel(
            ["BAIPP financial assistance subsidy", "individual processing projects",
             "खाद्य इकाई सहायता", "पूंजी सहायता"], "35%", QUOTE_EN,
        )
        chat = DashboardDocumentChat(lambda: nullcontext(query), lambda: model)
        answer = chat.ask(QUERY_HI, "hi")
        self.assertEqual(answer["document_chat"]["status"], "no_evidence")
        self.assertEqual(answer["sources"], [])
        self.assertEqual([name for name, _ in model.calls], ["QuestionSuggestions"])

    def test_unknown_explicit_acronym_is_not_replaced_by_a_known_scheme(self):
        row = pinned_row(SOURCE_EN, 11, 0)
        query = Mock()
        query.search_agriculture_documents.return_value = [row]
        results = MongoDocumentRetriever(query).retrieve_documents({
            "question": "What is the ZZQX processing subsidy in the BAIPP brochure?",
            "subQuestions": ["PMFME processing grant", "PMFME credit subsidy", "प्रसंस्करण सहायता", "वित्तीय अनुदान"],
        })
        self.assertEqual(results["retrieved_documents"], [])

    def test_span_selection_copies_real_source_punctuation_not_model_paraphrase(self):
        from pydantic import ValidationError

        sample = pinned_row(SOURCE_EN, 11)
        variants = ["PMFME subsidy cost maximum", "PMFME credit-linked subsidy units",
                    "पीएमएफएमई योजना राशि", "खाद्य सहायता"]
        chat, _, model = self.fixture(
            sample, "pmfme", "पात्र लागत पर 35% सहायता और अधिकतम Rs. 10 लाख।", QUOTE_EN, variants,
        )
        result = chat.ask(QUERY_HI, "hi")
        self.assertEqual(result["document_chat"]["status"], "cited")
        self.assertIn("Rs. 10", result["answer"])
        offered = result["records"][0]["content"]
        self.assertIn("Rs.10", offered)
        self.assertIn("35%", offered)
        self.assertNotIn("Rs. 10", offered)
        self.assertIn(offered, " ".join(sample["content"].split()))
        self.assertEqual(result["records"][0]["page_number"], 11)
        self.assertEqual(result["records"][0]["chunk_index"], 0)
        self.assertEqual(_GroundedAnswer.model_json_schema()["properties"]["evidence"]["items"]["type"], "integer")
        with self.assertRaises(ValidationError):
            _GroundedAnswer.model_validate({"evidence": [{"passage": 1, "quote": offered}]})
        with self.assertRaises(ValidationError):
            _GroundedAnswer.model_validate({"evidence": ["1"]})

    def test_source_span_split_keeps_decimal_and_currency_abbreviation_intact(self):
        source = ("A long setup sentence. Rate was 4.5%. Assistance per unit is Rs. 10 lakh "
                  "where applicable. पात्रता लागू है। अगली सूचना स्पष्ट है।")
        spans = list(_sentence_spans(source))
        self.assertTrue(any("Rs. 10 lakh where applicable." in item for item in spans))
        self.assertTrue(any("4.5%" in item for item in spans))
        self.assertTrue(all(item in source and len(item) <= 400 for item in spans))

    def test_missing_hindi_summary_is_rendered_using_only_selected_source_excerpt(self):
        sample = pinned_row(SOURCE_EN, 11)
        chat, _, model = self.fixture(
            sample, "pmfme", "", QUOTE_EN,
            ["PMFME coverage", "PMFME individual subsidy", "खाद्य इकाई सहायता", "पूंजी अनुदान"],
        )
        model.rendered_summary = "पात्र परियोजना लागत पर ३५ प्रतिशत सहायता है, अधिकतम १० लाख रुपये प्रति इकाई।"
        result = chat.ask(QUERY_HI, "hi")
        self.assertEqual(result["document_chat"]["status"], "cited")
        self.assertEqual(result["document_chat"]["summary"], {"initial": "missing", "render": "accepted"})
        self.assertEqual(result["answer"], model.rendered_summary)
        self.assertIn(QUOTE_EN, result["records"][0]["content"])
        self.assertEqual(result["records"][0]["page_number"], 11)
        self.assertEqual([schema for schema, _ in model.calls],
                         ["QuestionSuggestions", "_GroundedAnswer", "_RenderedSummary"])
        selection_input = model.calls[1][1][-1].content
        render_input = model.calls[-1][1][-1].content
        self.assertIn("Key Objective of PMFME", selection_input)
        self.assertNotIn("Key Objective of PMFME", render_input)
        self.assertIn("Selected excerpts:", render_input)
        self.assertIn(QUOTE_EN, render_input)
        self.assertIn("Hindi in Devanagari", model.calls[-1][1][0].content)
        self.assertEqual(set(_RenderedSummary.model_json_schema()["properties"]), {"summary"})

    def test_valid_initial_summary_has_no_render_call(self):
        sample = pinned_row(SOURCE_EN, 11)
        chat, _, model = self.fixture(
            sample, "pmfme", "पात्र लागत पर 35% सहायता, अधिकतम ₹10 लाख प्रति इकाई।", QUOTE_EN,
            ["PMFME coverage", "PMFME individual subsidy", "खाद्य इकाई सहायता", "पूंजी अनुदान"],
        )
        result = chat.ask(QUERY_HI)
        self.assertEqual(result["document_chat"]["summary"], {"initial": "accepted", "render": "not_attempted"})
        self.assertEqual([schema for schema, _ in model.calls], ["QuestionSuggestions", "_GroundedAnswer"])

    def test_rejected_initial_summary_reports_reason_and_render_keeps_numbers_and_units(self):
        sample = pinned_row(SOURCE_EN, 11)
        chat, _, model = self.fixture(
            sample, "pmfme", "PMFME support is 35% up to 10 lakh rupees.", QUOTE_EN,
            ["PMFME coverage", "PMFME individual subsidy", "खाद्य इकाई सहायता", "पूंजी अनुदान"],
        )
        model.rendered_summary = "परियोजना लागत पर 35% सहायता और अधिकतम 10 करोड़ रुपये प्रति इकाई।"
        result = chat.ask(QUERY_HI, "hi")
        self.assertEqual(result["document_chat"]["status"], "evidence_only")
        self.assertEqual(result["document_chat"]["summary"],
                         {"initial": "wrong_language", "render": "unsupported_amount_unit"})
        self.assertNotIn("करोड़", result["answer"])
        self.assertIn("Rs.10 lakh", result["records"][0]["content"])
        model.rendered_summary = "अधिकतम ₹35 लाख और 10 प्रतिशत सहायता मिलती है।"
        result = chat.ask(QUERY_HI, "hi")
        self.assertEqual(result["document_chat"]["summary"]["render"], "unsupported_amount_unit")
        model.rendered_summary = "अधिकतम ₹99 लाख प्रति इकाई है।"
        result = chat.ask(QUERY_HI, "hi")
        self.assertEqual(result["document_chat"]["summary"]["render"], "unsupported_number")

    def test_optional_render_timeout_cannot_take_away_verified_source(self):
        sample = pinned_row(SOURCE_EN, 11)
        chat, _, model = self.fixture(
            sample, "pmfme", "", QUOTE_EN,
            ["PMFME coverage", "PMFME individual subsidy", "खाद्य इकाई सहायता", "पूंजी अनुदान"],
        )
        model.render_error = DocumentChatUnavailable("Do not expose internals")
        result = chat.ask(QUERY_HI, "hi")
        self.assertEqual(result["document_chat"]["status"], "evidence_only")
        self.assertEqual(result["document_chat"]["summary"], {"initial": "missing", "render": "unavailable"})
        self.assertIn(QUOTE_EN, result["records"][0]["content"])
        self.assertNotIn("internals", result["answer"])

    @patch("services.dashboard_document_chat.monotonic", side_effect=[0, 115, 149])
    @patch("httpx.Client")
    def test_summary_can_start_with_remaining_budget_but_skips_when_nearly_exhausted(self, factory, clock):
        client = factory.return_value.__enter__.return_value
        response = httpx.Response(
            200, request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
            json={"message": {"content": '{"summary":""}'}},
        )
        client.post.return_value = response
        render = _LocalOllama("http://127.0.0.1:11434", "test").with_structured_output(_RenderedSummary)
        self.assertEqual(render.invoke([]).summary, "")
        self.assertEqual(factory.call_args.kwargs["timeout"].read, 35)
        self.assertEqual(client.post.call_args.kwargs["json"]["options"]["num_predict"], 240)
        with self.assertRaisesRegex(DocumentChatUnavailable, "time limit"):
            render.invoke([])
        self.assertEqual(client.post.call_count, 1)
