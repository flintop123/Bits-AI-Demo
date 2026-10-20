import unittest

from services.agriculture_qa_service import AgricultureQAService
from services.multilingual_query_expansion import expand_document_query


class FakeHindiQueryService:
    def __init__(self):
        self.search = None

    def list_values(self):
        return {
            "mandi_crops": [],
            "districts": [],
            "statistical_crops": [],
            "seasons": [],
        }

    def search_agriculture_documents(
        self, search_terms, limit, semantic_query=None
    ):
        self.search = (search_terms, limit, semantic_query)
        return [{
            "document_title": "मखाना रिपोर्ट",
            "page_number": 7,
            "chunk_index": 0,
            "content": "बिहार भारत में मखाना उत्पादन का प्रमुख राज्य है।",
            "source_url": "https://example.test/makhana.pdf",
            "source_file": "makhana.pdf",
            "source_organization": "Test Department",
            "language": "hi",
        }]

    def find_mandi_prices(self, filters, limit):
        raise AssertionError("Mandi data should not be queried")

    def find_crop_statistics(self, filters, limit):
        raise AssertionError("Crop statistics should not be queried")


class FakeHindiLLM:
    model = "fake-model"

    def chat_json(self, messages, schema):
        if schema.get("title") == "QueryPlan":
            return {
                "intent": "document_search",
                "search_terms": "मखाना उत्पादन बिहार",
                "metric": "records",
                "language": "hi",
                "limit": 5,
            }
        return {"answer": "बिहार मखाना उत्पादन का एक प्रमुख राज्य है।"}


class WrongLanguageThenHindiLLM(FakeHindiLLM):
    def __init__(self):
        self.answer_calls = 0

    def chat_json(self, messages, schema):
        if schema.get("title") == "QueryPlan":
            return super().chat_json(messages, schema)
        self.answer_calls += 1
        if self.answer_calls == 1:
            return {"answer": "The records describe makhana production."}
        return {
            "answer": (
                "\u0930\u093f\u0915\u0949\u0930\u094d\u0921 \u092e\u0947\u0902 "
                "\u092e\u0916\u093e\u0928\u093e \u0909\u0924\u094d\u092a\u093e\u0926\u0928 "
                "\u0915\u093e \u0935\u0930\u094d\u0923\u0928 \u0939\u0948\u0964"
            )
        }

class AlwaysWrongLanguageLLM(FakeHindiLLM):
    def chat_json(self, messages, schema):
        if schema.get("title") == "QueryPlan":
            return super().chat_json(messages, schema)
        return {"answer": "The model responded in the wrong language."}


class CorridorQueryService(FakeHindiQueryService):
    def search_agriculture_documents(
        self, search_terms, limit, semantic_query=None
    ):
        self.search = (search_terms, limit, semantic_query)
        return [
            {
                "document_title": "Bihar Annual Scheme 2022-23",
                "page_number": 14,
                "chunk_index": 0,
                "content": (
                    "An organic corridor covers 13 districts along both "
                    "banks of the Ganga."
                ),
                "source_id": "bihar_annual_scheme_2022_23",
                "source_url": "https://example.test/annual.pdf",
                "source_file": "annual.pdf",
                "source_organization": "Government of Bihar",
                "language": "en",
                "retrieval": {
                    "mode": "hybrid",
                    "methods": ["keyword", "semantic"],
                },
            },
            {
                "document_title": "मखाना पुस्तिका",
                "page_number": 4,
                "chunk_index": 1,
                "content": "बिहार मखाना उत्पादन का प्रमुख राज्य है।",
                "source_id": "pmfme_makhana_handbook_hindi",
                "source_url": "https://example.test/makhana.pdf",
                "source_file": "makhana.pdf",
                "source_organization": "Test Department",
                "language": "hi",
                "retrieval": {
                    "mode": "semantic",
                    "methods": ["semantic"],
                },
            },
        ]


class CorridorTranslationLLM:
    model = "fake-model"

    def __init__(self):
        self.answer_prompts = []

    def chat_json(self, messages, schema):
        if schema.get("title") == "QueryPlan":
            return {
                "intent": "document_search",
                "search_terms": "गंगा जैविक कॉरिडोर जिलों की संख्या",
                "metric": "records",
                "language": "hi",
                "limit": 5,
            }
        prompt = messages[-1]["content"]
        self.answer_prompts.append(prompt)
        if len(self.answer_prompts) == 1:
            return {"answer": "The organic corridor covers 13 districts."}
        return {"answer": "जैविक कॉरिडोर 13 जिलों में स्थापित किया गया है।"}


class CorridorPlainTextTranslationLLM:
    model = "fake-model"

    def __init__(self):
        self.answer_calls = 0
        self.text_prompts = []

    def chat_json(self, messages, schema):
        if schema.get("title") == "QueryPlan":
            return {
                "intent": "document_search",
                "search_terms": "गंगा जैविक कॉरिडोर जिलों की संख्या",
                "metric": "records",
                "language": "hi",
                "limit": 5,
            }
        self.answer_calls += 1
        return {"answer": "The organic corridor covers 13 districts."}

    def chat_text(self, messages):
        self.text_prompts.append(messages[-1]["content"])
        return "जैविक कॉरिडोर गंगा के किनारे 13 जिलों में स्थापित है।"


class FakeLocalTranslator:
    def __init__(self):
        self.calls = []

    def translate(self, text, source_language, target_language):
        self.calls.append((text, source_language, target_language))
        return "जैविक कॉरिडोर गंगा के दोनों किनारों पर 13 जिलों में स्थापित है।"


class UnavailableTranslator:
    def translate(self, text, source_language, target_language):
        raise ValueError("Translation deliberately unavailable in this test")


class LocalTranslationLLM(CorridorPlainTextTranslationLLM):
    def chat_text(self, messages):
        raise AssertionError("Qwen language retry should not be needed")


class MetaAnswerLLM(LocalTranslationLLM):
    def chat_json(self, messages, schema):
        if schema.get("title") == "QueryPlan":
            return super().chat_json(messages, schema)
        self.answer_calls += 1
        return {
            "answer": (
                "The question is in Hindi and the user provided text from "
                "an agriculture report."
            )
        }


class NumericOnlyAnswerLLM(LocalTranslationLLM):
    def chat_json(self, messages, schema):
        if schema.get("title") == "QueryPlan":
            return super().chat_json(messages, schema)
        self.answer_calls += 1
        return {"answer": "13"}

    def chat_text(self, messages):
        raise AssertionError("Numeric answer should be formatted directly")

class HindiQATests(unittest.TestCase):
    def test_hindi_question_preserves_hindi_retrieval_terms_and_answer(self):
        query_service = FakeHindiQueryService()
        qa_service = AgricultureQAService(query_service, FakeHindiLLM())

        result = qa_service.ask("बिहार में मखाना उत्पादन के बारे में बताइए।")

        self.assertEqual(
            query_service.search,
            (
                expand_document_query(
                    "मखाना उत्पादन बिहार",
                    "बिहार में मखाना उत्पादन के बारे में बताइए।",
                    max_length=200,
                ),
                5,
                expand_document_query(
                    "बिहार में मखाना उत्पादन के बारे में बताइए।",
                    expand_document_query(
                        "मखाना उत्पादन बिहार",
                        "बिहार में मखाना उत्पादन के बारे में बताइए।",
                        max_length=200,
                    ),
                    max_length=500,
                ),
            ),
        )
        self.assertEqual(result["intent"], "document_search")
        self.assertIn("बिहार", result["answer"])
        self.assertEqual(result["sources"][0]["language"], "hi")
        self.assertEqual(result["sources"][0]["page_number"], 7)


    def test_wrong_answer_language_is_corrected_with_grounded_retry(self):
        llm = WrongLanguageThenHindiLLM()
        qa_service = AgricultureQAService(
            FakeHindiQueryService(), llm,
            translator=UnavailableTranslator(),
        )

        result = qa_service.ask(
            "\u092c\u093f\u0939\u093e\u0930 \u092e\u0947\u0902 \u092e\u0916\u093e\u0928\u093e "
            "\u0909\u0924\u094d\u092a\u093e\u0926\u0928 \u0915\u0947 \u092c\u093e\u0930\u0947 "
            "\u092e\u0947\u0902 \u092c\u0924\u093e\u0907\u090f\u0964"
        )

        self.assertEqual(llm.answer_calls, 2)
        self.assertIn("\u092e\u0916\u093e\u0928\u093e", result["answer"])
        self.assertNotIn("The records", result["answer"])

    def test_repeated_wrong_language_uses_grounded_source_fallback(self):
        qa_service = AgricultureQAService(
            FakeHindiQueryService(), AlwaysWrongLanguageLLM(),
            translator=UnavailableTranslator(),
        )

        result = qa_service.ask(
            "\u092c\u093f\u0939\u093e\u0930 \u092e\u0947\u0902 \u092e\u0916\u093e\u0928\u093e "
            "\u0909\u0924\u094d\u092a\u093e\u0926\u0928 \u0915\u0947 \u092c\u093e\u0930\u0947 "
            "\u092e\u0947\u0902 \u092c\u0924\u093e\u0907\u090f\u0964"
        )

        self.assertIn(
            "\u0909\u092a\u0932\u092c\u094d\u0927 \u0938\u094d\u0930\u094b\u0924\u094b\u0902 "
            "\u0915\u0947 \u0905\u0928\u0941\u0938\u093e\u0930",
            result["answer"],
        )
        self.assertIn(
            "\u092c\u093f\u0939\u093e\u0930 \u092d\u093e\u0930\u0924 \u092e\u0947\u0902 "
            "\u092e\u0916\u093e\u0928\u093e \u0909\u0924\u094d\u092a\u093e\u0926\u0928",
            result["answer"],
        )
        self.assertNotIn("wrong language", result["answer"])

    def test_cross_language_answer_uses_only_top_ranked_source(self):
        llm = CorridorTranslationLLM()
        qa_service = AgricultureQAService(
            CorridorQueryService(), llm,
            translator=UnavailableTranslator(),
        )

        result = qa_service.ask(
            "गंगा नदी के किनारे जैविक कॉरिडोर कितने जिलों में स्थापित किया गया है?",
            answer_language="hi",
        )

        self.assertIn("13", result["answer"])
        self.assertIn("जिलों", result["answer"])
        self.assertNotIn("मखाना", llm.answer_prompts[0])
        self.assertNotIn("मखाना", llm.answer_prompts[1])
        self.assertIn(
            "The organic corridor covers 13 districts.",
            llm.answer_prompts[1],
        )
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(
            result["sources"][0]["source_id"],
            "bihar_annual_scheme_2022_23",
        )
        self.assertNotIn(
            "makhana",
            str(result["sources"]).casefold(),
        )

    def test_plain_text_language_retry_avoids_json_language_failure(self):
        llm = CorridorPlainTextTranslationLLM()
        qa_service = AgricultureQAService(
            CorridorQueryService(), llm,
            translator=UnavailableTranslator(),
        )

        result = qa_service.ask(
            "गंगा नदी के किनारे जैविक कॉरिडोर कितने जिलों में स्थापित किया गया है?",
            answer_language="hi",
        )

        self.assertEqual(llm.answer_calls, 1)
        self.assertEqual(len(llm.text_prompts), 1)
        self.assertIn("13", result["answer"])
        self.assertIn("जिलों", result["answer"])
        self.assertNotIn("मखाना", llm.text_prompts[0])

    def test_local_translation_precedes_additional_qwen_retry(self):
        llm = LocalTranslationLLM()
        translator = FakeLocalTranslator()
        qa_service = AgricultureQAService(
            CorridorQueryService(), llm, translator=translator
        )

        result = qa_service.ask(
            "गंगा नदी के किनारे जैविक कॉरिडोर कितने जिलों में स्थापित किया गया है?",
            answer_language="hi",
        )

        self.assertEqual(len(translator.calls), 1)
        self.assertEqual(translator.calls[0][1:], ("en", "hi"))
        self.assertIn("13", result["answer"])
        self.assertIn("दोनों किनारों", result["answer"])

    def test_meta_answer_is_replaced_by_top_source_before_translation(self):
        llm = MetaAnswerLLM()
        translator = FakeLocalTranslator()
        qa_service = AgricultureQAService(
            CorridorQueryService(), llm, translator=translator
        )

        result = qa_service.ask(
            "गंगा नदी के किनारे जैविक कॉरिडोर कितने जिलों में स्थापित किया गया है?",
            answer_language="hi",
        )

        translated_text = translator.calls[0][0]
        self.assertIn("organic corridor covers 13 districts", translated_text)
        self.assertNotIn("The question is in Hindi", translated_text)
        self.assertIn("13", result["answer"])

    def test_numeric_only_answer_is_formatted_in_requested_language(self):
        llm = NumericOnlyAnswerLLM()
        translator = UnavailableTranslator()
        qa_service = AgricultureQAService(
            CorridorQueryService(), llm, translator=translator
        )

        result = qa_service.ask(
            "गंगा नदी के किनारे जैविक कॉरिडोर कितने जिलों में स्थापित किया गया है?",
            answer_language="hi",
        )

        self.assertEqual(llm.answer_calls, 1)
        self.assertIn("13 जिलों", result["answer"])
        self.assertIn("आधिकारिक स्रोत", result["answer"])

if __name__ == "__main__":
    unittest.main()
