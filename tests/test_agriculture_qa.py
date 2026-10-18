import unittest

from data_api import create_app
from services.agriculture_qa_service import AgricultureQAService
from services.ollama_client import OllamaUnavailableError


class FakeQueryService:
    def __init__(self):
        self.mandi_call = None
        self.statistics_call = None

    def list_values(self):
        return {
            "mandi_crops": ["Potato", "Onion"],
            "districts": ["Arwal"],
            "statistical_crops": ["Rice", "Wheat"],
            "seasons": ["Kharif", "Rabi", "Total"],
        }

    def find_mandi_prices(self, filters, limit):
        self.mandi_call = (filters, limit)
        return [{
            "district": "Arwal",
            "market": "Arwal",
            "date": "2026-10-17",
            "crop": "Potato",
            "price": 1200.0,
            "unit": "quintal",
            "source_url": "https://example.test/mandi",
        }]

    def find_crop_statistics(self, filters, limit):
        self.statistics_call = (filters, limit)
        return [{
            "crop": "Rice",
            "season": "Kharif",
            "year": "2024-25",
            "area_hectares": 100,
            "production": 200,
            "production_unit": "tonne",
            "yield_kg_per_hectare": 2000,
            "source": "Department of Agriculture & Farmers Welfare",
            "source_file": "crop.xlsx",
        }]


class FakeLLM:
    model = "fake-model"

    def __init__(self, plan, answer="Grounded answer"):
        self.plan = plan
        self.answer = answer
        self.calls = 0

    def chat_json(self, messages, schema):
        self.calls += 1
        if schema.get("title") == "QueryPlan":
            return self.plan
        return {"answer": self.answer}


class FailingLLM:
    model = "fake-model"

    def chat_json(self, messages, schema):
        raise OllamaUnavailableError("Ollama unavailable for test")


class AgricultureQAServiceTests(unittest.TestCase):
    def test_mandi_question_uses_allowlisted_filters(self):
        database = FakeQueryService()
        llm = FakeLLM({
            "intent": "mandi_price",
            "crop": "potato",
            "district": "arwal",
            "metric": "price",
            "language": "en",
            "limit": 3,
        })
        service = AgricultureQAService(database, llm)

        result = service.ask("What is the potato price in Arwal?")

        self.assertEqual(
            database.mandi_call,
            ({"district": "Arwal", "crop": "Potato"}, 3),
        )
        self.assertEqual(result["answer"], "Grounded answer")
        self.assertEqual(result["model"], "fake-model")
        self.assertEqual(len(result["sources"]), 1)

    def test_statistics_question_queries_crop_season_and_year(self):
        database = FakeQueryService()
        llm = FakeLLM({
            "intent": "crop_statistics",
            "crop": "rice",
            "season": "kharif",
            "year": "2024-25",
            "metric": "yield",
            "language": "en",
            "limit": 5,
        })
        service = AgricultureQAService(database, llm)

        result = service.ask("Rice yield in Kharif 2024-25")

        self.assertEqual(
            database.statistics_call,
            ({"crop": "Rice", "season": "Kharif", "year": "2024-25"}, 5),
        )
        self.assertEqual(result["intent"], "crop_statistics")

    def test_unsupported_question_does_not_query_database(self):
        database = FakeQueryService()
        llm = FakeLLM({
            "intent": "unsupported",
            "metric": "records",
            "language": "en",
            "limit": 5,
        })
        service = AgricultureQAService(database, llm)

        result = service.ask("Will it rain tomorrow?")

        self.assertEqual(result["intent"], "unsupported")
        self.assertIsNone(database.mandi_call)
        self.assertIsNone(database.statistics_call)
        self.assertEqual(llm.calls, 1)

    def test_empty_question_is_rejected_before_model_call(self):
        service = AgricultureQAService(
            FakeQueryService(),
            FakeLLM({"intent": "unsupported"}),
        )
        with self.assertRaisesRegex(ValueError, "question is required"):
            service.ask("   ")

    def test_ask_endpoint_returns_grounded_payload(self):
        database = FakeQueryService()
        qa_service = AgricultureQAService(
            database,
            FakeLLM({
                "intent": "crop_statistics",
                "crop": "Rice",
                "year": "2024-25",
                "metric": "production",
                "language": "en",
                "limit": 2,
            }),
        )
        client = create_app(database, qa_service).test_client()

        response = client.post(
            "/api/v1/ask",
            json={"question": "Rice production in 2024-25"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["records"][0]["crop"], "Rice")
        self.assertEqual(response.json["filters"]["year"], "2024-25")

    def test_ollama_failure_returns_503(self):
        database = FakeQueryService()
        qa_service = AgricultureQAService(database, FailingLLM())
        client = create_app(database, qa_service).test_client()

        response = client.post(
            "/api/v1/ask",
            json={"question": "Show rice production"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("Ollama unavailable", response.json["error"])

    def test_answer_language_can_override_detected_question_language(self):
        database = FakeQueryService()
        llm = FakeLLM({
            "intent": "crop_statistics",
            "crop": "Rice",
            "year": "2024-25",
            "metric": "production",
            "language": "hi",
            "limit": 2,
        }, answer="Rice production was 200 tonnes.")
        service = AgricultureQAService(database, llm)

        result = service.ask(
            "2024-25 में चावल का उत्पादन कितना था?",
            answer_language="en",
        )

        self.assertEqual(result["answer_language"], "en")
        self.assertIn("Rice", result["answer"])

    def test_invalid_answer_language_is_rejected(self):
        service = AgricultureQAService(
            FakeQueryService(), FakeLLM({"intent": "unsupported"})
        )
        with self.assertRaisesRegex(ValueError, "auto, en, or hi"):
            service.ask("Rice production", answer_language="fr")


if __name__ == "__main__":
    unittest.main()
