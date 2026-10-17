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


if __name__ == "__main__":
    unittest.main()
