import unittest
from unittest.mock import Mock

from data_api import create_app
from services.agriculture_qa_service import AgricultureQAService
from services.agriculture_query_service import AgricultureQueryService
from services.multilingual_query_expansion import expand_document_query


DOCUMENT_RECORD = {
    "document_title": "Bihar Annual Scheme 2022-23",
    "page_number": 13,
    "chunk_index": 1,
    "content": "An organic corridor is established along the Ganga.",
    "source_url": "https://example.test/report.pdf",
    "source_file": "report.pdf",
    "score": 2.5,
}


class FakeQueryService:
    def __init__(self):
        self.document_call = None

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
        self.document_call = (search_terms, limit, semantic_query)
        return [DOCUMENT_RECORD]

    def find_mandi_prices(self, filters, limit):
        raise AssertionError("Mandi data should not be queried")

    def find_crop_statistics(self, filters, limit):
        raise AssertionError("Crop statistics should not be queried")


class FakeLLM:
    model = "fake-model"

    def chat_json(self, messages, schema):
        if schema.get("title") == "QueryPlan":
            return {
                "intent": "document_search",
                "search_terms": "organic farming corridor",
                "metric": "records",
                "language": "en",
                "limit": 3,
            }
        return {"answer": "The report describes an organic corridor."}


class DocumentSearchTests(unittest.TestCase):
    def test_query_service_uses_ranked_mongodb_text_search(self):
        collection = Mock()
        cursor = Mock()
        sorted_cursor = Mock()
        collection.find.return_value = cursor
        cursor.sort.return_value = sorted_cursor
        sorted_cursor.limit.return_value = [DOCUMENT_RECORD]

        service = AgricultureQueryService.__new__(AgricultureQueryService)
        service.agriculture_documents = collection
        records = service.search_agriculture_documents("organic farming", 4)

        self.assertEqual(records[0]["content"], DOCUMENT_RECORD["content"])
        self.assertEqual(records[0]["retrieval"]["mode"], "keyword")
        query = collection.find.call_args.args[0]
        self.assertEqual(query, {"$text": {"$search": "organic farming"}})
        sorted_cursor.limit.assert_called_once_with(32)

    def test_blank_document_search_is_rejected(self):
        service = AgricultureQueryService.__new__(AgricultureQueryService)
        service.agriculture_documents = Mock()
        with self.assertRaisesRegex(ValueError, "search terms are required"):
            service.search_agriculture_documents("  ", 5)

    def test_document_api_returns_page_aware_results(self):
        service = Mock()
        service.search_agriculture_documents.return_value = [DOCUMENT_RECORD]
        client = create_app(service, Mock()).test_client()
        response = client.get(
            "/api/v1/documents/search?q=organic%20farming&limit=3"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["records"][0]["page_number"], 13)
        expanded = expand_document_query("organic farming", max_length=200)
        service.search_agriculture_documents.assert_called_once_with(
            expanded,
            3,
            semantic_query=expand_document_query(
                "organic farming", max_length=500
            ),
        )

    def test_document_api_rejects_missing_query(self):
        service = Mock()
        service.search_agriculture_documents.side_effect = ValueError(
            "search terms are required"
        )
        client = create_app(service, Mock()).test_client()
        response = client.get("/api/v1/documents/search")

        self.assertEqual(response.status_code, 400)
        self.assertIn("search terms", response.json["error"])

    def test_natural_language_question_uses_document_search(self):
        query_service = FakeQueryService()
        qa_service = AgricultureQAService(query_service, FakeLLM())
        result = qa_service.ask(
            "What does the report say about the organic farming corridor?"
        )

        self.assertEqual(
            query_service.document_call,
            (
                expand_document_query(
                    "organic farming corridor",
                    "What does the report say about the organic farming corridor?",
                    max_length=200,
                ),
                3,
                expand_document_query(
                    "What does the report say about the organic farming corridor?",
                    expand_document_query(
                        "organic farming corridor",
                        "What does the report say about the organic farming corridor?",
                        max_length=200,
                    ),
                    max_length=500,
                ),
            ),
        )
        self.assertEqual(result["intent"], "document_search")
        self.assertEqual(result["sources"][0]["page_number"], 13)
        self.assertEqual(
            result["filters"],
            {
                "search_terms": expand_document_query(
                    "organic farming corridor",
                    "What does the report say about the organic farming corridor?",
                    max_length=200,
                )
            },
        )


if __name__ == "__main__":
    unittest.main()
