import unittest

from pydantic import ValidationError

from services.catalog_translation_agent import (
    CatalogTranslationAgent,
    CatalogTranslationError,
    CatalogTranslationInput,
)


class FakeLLM:
    model = "qwen3:4b"

    def __init__(self, label):
        self.label = label
        self.calls = []

    def chat_json(self, messages, schema):
        self.calls.append((messages, schema))
        return {"translated_label": self.label}


class FakeBackTranslator:
    def __init__(self, round_trip):
        self.round_trip = round_trip

    def translate(self, text, source_language, target_language):
        return self.round_trip

    @staticmethod
    def translation_metadata(source_language, target_language):
        return {"model_name": "test/back-translator"}


class CatalogTranslationAgentTests(unittest.TestCase):
    def test_qwen_candidate_is_accepted_only_after_independent_round_trip(self):
        agent = CatalogTranslationAgent(
            llm=FakeLLM("Turmeric"),
            back_translator=FakeBackTranslator("हल्दी"),
        )

        result = agent.translate({
            "official_value": "हल्दी",
            "entity_type": "crop",
            "source_language": "hi",
            "target_language": "en",
        })

        self.assertTrue(result.accepted)
        self.assertEqual(result.translated_label, "Turmeric")
        self.assertEqual(result.round_trip_candidate, "हल्दी")
        self.assertEqual(
            result.translation_evidence["validation_status"],
            "accepted_independent_round_trip_match",
        )
        self.assertEqual(
            result.translation_evidence["validation_model"],
            "test/back-translator",
        )

    def test_qwen_candidate_is_rejected_after_round_trip_mismatch(self):
        agent = CatalogTranslationAgent(
            llm=FakeLLM("Total"),
            back_translator=FakeBackTranslator("हल नहीं कर सका"),
        )

        result = agent.translate({
            "official_value": "हल्दी",
            "entity_type": "crop",
            "source_language": "hi",
            "target_language": "en",
        })

        self.assertFalse(result.accepted)
        self.assertIsNone(result.translated_label)
        self.assertEqual(result.proposed_label, "Total")

    def test_market_semantic_translation_is_rejected(self):
        agent = CatalogTranslationAgent(
            llm=FakeLLM("Test market"),
            back_translator=FakeBackTranslator("परीक्षण मंडी"),
        )

        with self.assertRaisesRegex(
            CatalogTranslationError, "Market proper names"
        ):
            agent.translate({
                "official_value": "परीक्षण मंडी",
                "entity_type": "market",
                "source_language": "hi",
                "target_language": "en",
            })

    def test_input_schema_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError):
            CatalogTranslationInput.model_validate({
                "official_value": "हल्दी",
                "entity_type": "crop",
                "source_language": "hi",
                "target_language": "en",
                "unexpected": True,
            })

    def test_tool_contract_exposes_input_and_output_json_schema(self):
        schemas = CatalogTranslationAgent.tool_schemas()

        self.assertIn("properties", schemas["input"])
        self.assertIn("properties", schemas["output"])
        self.assertIn("official_value", schemas["input"]["properties"])
        self.assertIn("accepted", schemas["output"]["properties"])


if __name__ == "__main__":
    unittest.main()
