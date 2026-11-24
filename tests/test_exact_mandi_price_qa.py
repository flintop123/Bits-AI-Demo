import unittest
from unittest.mock import Mock

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from data_api import create_app
from services.agriculture_qa_service import AgricultureQAService
from services.ollama_client import OllamaUnavailableError
from services.viva_dashboard import ReactDashboard


ENGLISH = "What is the potato price in Arwal mandi?"
HINDI = "अरवल मंडी में आलू का भाव क्या है?"
CATALOG = {
    "mandi_crops": ["आलू", "पपीता"],
    "markets": ["अरवल", "दाउनगर"],
    "districts": ["अरवल", "औरंगाबाद"],
}
SOURCE = "https://www.biharkrishi.in/mandi"
LATEST = {
    "crop": "आलू", "market": "अरवल", "district": "अरवल",
    "date": "2026-10-23", "price": 1400.0, "variety": "Desi",
    "unit": "quintal", "source_price_unit": "Rs/Quintal", "source_url": SOURCE,
}


class ToolCallingModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        assert [tool.name for tool in tools] == ["ask_agriculture_question"]
        return self


class ExactMandiPriceTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.list_values.return_value = CATALOG
        self.db.find_mandi_prices.return_value = [
            LATEST,
            {**LATEST, "date": "2026-10-17", "price": 1200.0,
             "source_url": "https://example.test/older"},
        ]
        self.llm = Mock(model="test-model")
        self.qa = AgricultureQAService(self.db, self.llm)

    def test_english_ignores_planner_wrong_crop_even_if_it_is_in_catalog(self):
        self.llm.chat_json.return_value = {"intent": "mandi_price", "crop": "पपीता"}
        result = self.qa.ask(ENGLISH)
        self.db.find_mandi_prices.assert_called_once_with(
            {"market": "अरवल", "crop": "आलू"}, 5,
        )
        self.llm.chat_json.assert_not_called()
        self.assertEqual(result["filters"], {"market": "अरवल", "crop": "आलू"})
        self.assertEqual(result["records"], [LATEST])
        self.assertEqual(result["sources"], [{"source": SOURCE}])
        self.assertIn("2026-10-23", result["answer"])
        self.assertIn("1400.0 Rs/Quintal (Desi)", result["answer"])
        self.assertNotIn("1200", result["answer"])

    def test_hindi_works_without_structured_model_json_for_plan_or_answer(self):
        self.llm.chat_json.side_effect = OllamaUnavailableError(
            "Ollama did not return the requested structured JSON."
        )
        result = self.qa.ask(HINDI)
        self.assertEqual(result["answer_language"], "hi")
        self.assertIn("अरवल मंडी में आलू का नवीनतम दर्ज भाव", result["answer"])
        self.assertIn("1400.0 Rs/Quintal", result["answer"])
        self.assertEqual(result["sources"], [{"source": SOURCE}])
        self.llm.chat_json.assert_not_called()
        self.assertEqual(self.qa.ask(HINDI, "en")["answer_language"], "en")

    def test_no_record_means_no_price_and_no_model_call(self):
        self.db.find_mandi_prices.return_value = []
        result = self.qa.ask(ENGLISH)
        self.assertEqual(result["filters"], {"market": "अरवल", "crop": "आलू"})
        self.assertEqual(result["records"], [])
        self.assertEqual(result["sources"], [])
        self.assertIn("No matching records", result["answer"])
        self.llm.chat_json.assert_not_called()

    def test_partial_or_ambiguous_request_is_not_chosen_as_exact_lookup(self):
        self.llm.chat_json.side_effect = OllamaUnavailableError("invalid JSON")
        for question in (
            "What is the potato price in Arwal mandi on 2026-10-17?",
            "What is the Desi potato price in Arwal mandi?",
            "What is the potato and papaya price in Arwal mandi?",
            "What is the potato price in Arwal, not Daudnagar mandi?",
            "What is the potato price in Arwal or Daudnagar mandi?",
            "अरवल मंडी में आलू और पपीता का भाव क्या है?",
            "अरवल मंडी में 2026-10-17 को आलू का भाव क्या है?",
            "What is the potato price in Aurangabad mandi?",
        ):
            with self.subTest(question=question), self.assertRaisesRegex(
                OllamaUnavailableError, "invalid JSON",
            ):
                self.qa.ask(question)
        self.assertEqual(self.llm.chat_json.call_count, 8)
        self.db.find_mandi_prices.assert_not_called()

    def test_direct_and_existing_react_endpoint_use_same_filtered_record(self):
        model = ToolCallingModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "ask_agriculture_question", "args": {}, "id": "lookup",
            }]),
        ])
        client = create_app(
            self.db, self.qa, viva_react=ReactDashboard(self.qa, llm=model),
        ).test_client()
        direct = client.post("/api/v1/ask", json={"question": ENGLISH})
        react = client.post("/api/v1/viva/react", json={"question": ENGLISH},
                            headers={"X-Agri-Dashboard": "1"})
        self.assertEqual(direct.status_code, 200, direct.json)
        self.assertEqual(react.status_code, 200, react.json)
        self.assertTrue(react.json["react"]["tool_called"])
        for key in ("answer", "filters", "records", "sources"):
            self.assertEqual(direct.json[key], react.json[key])
        self.llm.chat_json.assert_not_called()
