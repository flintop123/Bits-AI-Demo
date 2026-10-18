import unittest
from unittest.mock import Mock

from services.agriculture_query_service import AgricultureQueryService


def record(source_id, page, similarity=None):
    value = {
        "source_id": source_id,
        "source_url": f"https://example.test/{source_id}.pdf",
        "page_number": page,
        "chunk_index": 0,
        "content": f"Evidence from {source_id}",
        "content_hash": f"hash-{source_id}-{page}",
    }
    if similarity is not None:
        value["semantic_similarity"] = similarity
        value["embedding_model"] = "bge-m3"
    return value


class HybridRetrievalTests(unittest.TestCase):
    def test_rrf_combines_keyword_and_semantic_ranks(self):
        keyword = [record("source-a", 1), record("source-b", 2)]
        semantic = [
            record("source-b", 2, 0.91),
            record("source-c", 3, 0.82),
        ]

        results = AgricultureQueryService._fuse_document_results(
            keyword, semantic, 5
        )

        self.assertEqual(results[0]["source_id"], "source-b")
        self.assertEqual(results[0]["retrieval"]["mode"], "hybrid")
        self.assertEqual(
            results[0]["retrieval"]["methods"],
            ["keyword", "semantic"],
        )

    def test_semantic_only_result_is_retained(self):
        results = AgricultureQueryService._fuse_document_results(
            [], [record("hindi-source", 7, 0.88)], 5
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_id"], "hindi-source")
        self.assertEqual(results[0]["retrieval"]["mode"], "semantic")

    def test_semantic_search_skips_stale_embeddings(self):
        collection = Mock()
        collection.find.return_value = [{
            "source_id": "stale",
            "source_url": "https://example.test/stale.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "content": "old content",
            "content_hash": "current-hash",
            "embedding": [1.0, 0.0],
            "embedding_model": "bge-m3",
            "embedding_content_hash": "old-hash",
        }]
        embedder = Mock()
        embedder.model = "bge-m3"
        embedder.embed_query.return_value = [1.0, 0.0]
        service = AgricultureQueryService.__new__(AgricultureQueryService)
        service.agriculture_documents = collection
        service._embedding_client = embedder

        results = service._semantic_document_search("query", 5)

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
