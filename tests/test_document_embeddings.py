import unittest
from unittest.mock import Mock

from build_document_embeddings import DocumentEmbeddingIndexer


class FakeEmbedder:
    model = "bge-m3"

    def embed_texts(self, texts):
        return [[1.0, 0.0] for _ in texts]


class DocumentEmbeddingIndexerTests(unittest.TestCase):
    def test_only_missing_or_stale_documents_are_embedded(self):
        collection = Mock()
        collection.find.return_value = [
            {
                "_id": 1,
                "content": "Current text",
                "content_hash": "one",
                "embedding": [1.0, 0.0],
                "embedding_model": "bge-m3",
                "embedding_content_hash": "one",
            },
            {
                "_id": 2,
                "content": "New text",
                "content_hash": "two",
            },
        ]
        collection.bulk_write.return_value = Mock()

        summary = DocumentEmbeddingIndexer(
            collection, FakeEmbedder()
        ).run(batch_size=4)

        self.assertEqual(summary["documents_total"], 2)
        self.assertEqual(summary["documents_embedded"], 1)
        self.assertEqual(summary["documents_current"], 1)
        collection.bulk_write.assert_called_once()

    def test_invalid_batch_size_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 64"):
            DocumentEmbeddingIndexer(Mock(), FakeEmbedder()).run(
                batch_size=0
            )


if __name__ == "__main__":
    unittest.main()
