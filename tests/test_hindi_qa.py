import unittest

from services.agriculture_qa_service import AgricultureQAService


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

    def search_agriculture_documents(self, search_terms, limit):
        self.search = (search_terms, limit)
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

class HindiQATests(unittest.TestCase):
    def test_hindi_question_preserves_hindi_retrieval_terms_and_answer(self):
        query_service = FakeHindiQueryService()
        qa_service = AgricultureQAService(query_service, FakeHindiLLM())

        result = qa_service.ask("बिहार में मखाना उत्पादन के बारे में बताइए।")

        self.assertEqual(
            query_service.search,
            ("मखाना उत्पादन बिहार", 5),
        )
        self.assertEqual(result["intent"], "document_search")
        self.assertIn("बिहार", result["answer"])
        self.assertEqual(result["sources"][0]["language"], "hi")
        self.assertEqual(result["sources"][0]["page_number"], 7)


    def test_wrong_answer_language_is_corrected_with_grounded_retry(self):
        llm = WrongLanguageThenHindiLLM()
        qa_service = AgricultureQAService(FakeHindiQueryService(), llm)

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
            FakeHindiQueryService(), AlwaysWrongLanguageLLM()
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

if __name__ == "__main__":
    unittest.main()
