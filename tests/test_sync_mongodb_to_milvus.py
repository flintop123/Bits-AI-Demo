import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pymilvus import DataType

from sync_mongodb_to_milvus import (
    MongoToMilvusIndexer,
    _chunks_by_utf8_size,
    _get_or_create_milvus_collection,
)


class FakeField:
    def __init__(
        self,
        name,
        dtype,
        *,
        primary=False,
        params=None,
        auto_id=False,
    ):
        self.name = name
        self.dtype = dtype
        self.is_primary = primary
        self.params = params or {}
        self.auto_id = auto_id


class FakeMilvusCollection:
    name = "configured_collection"

    def __init__(self):
        self.schema = SimpleNamespace(
            fields=[
                FakeField(
                    "pk",
                    DataType.VARCHAR,
                    primary=True,
                    params={"max_length": 64},
                ),
                FakeField(
                    "text_content",
                    DataType.VARCHAR,
                    params={"max_length": 4000},
                ),
                FakeField(
                    "embedding",
                    DataType.FLOAT_VECTOR,
                    params={"dim": 3},
                ),
                FakeField("source", DataType.VARCHAR),
                FakeField("metadata", DataType.JSON),
            ],
            enable_dynamic_field=False,
            auto_id=False,
        )
        self.upserts = []

    def upsert(self, rows):
        self.upserts.extend(rows)


class FakeMongoCollection:
    def __init__(self, documents):
        self.documents = documents

    def find(self, query):
        self.asserted_query = query
        return iter(self.documents)


class FakeMongoDatabase:
    def __init__(self, collections):
        self.collections = collections

    def list_collection_names(self):
        return list(self.collections)

    def __getitem__(self, name):
        return self.collections[name]


class FakeEmbedder:
    model = "test-embedding-model"

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]

    def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class MongoToMilvusTests(unittest.TestCase):
    @patch("sync_mongodb_to_milvus.Collection")
    @patch("sync_mongodb_to_milvus.utility.has_collection", return_value=True)
    def test_existing_collection_is_reused_without_creating_schema(
        self,
        has_collection,
        collection_factory,
    ):
        existing_collection = Mock()
        collection_factory.return_value = existing_collection

        result, created = _get_or_create_milvus_collection(
            "configured_collection",
            "sync-alias",
            {"collectionName": "configured_collection"},
            FakeEmbedder(),
        )

        self.assertIs(result, existing_collection)
        self.assertFalse(created)
        has_collection.assert_called_once_with(
            "configured_collection",
            using="sync-alias",
        )
        existing_collection.create_index.assert_not_called()

    @patch("sync_mongodb_to_milvus.Collection")
    @patch("sync_mongodb_to_milvus.utility.has_collection", return_value=False)
    def test_missing_collection_is_created_with_configured_name(
        self,
        has_collection,
        collection_factory,
    ):
        new_collection = Mock()
        collection_factory.return_value = new_collection

        result, created = _get_or_create_milvus_collection(
            "configured_collection",
            "sync-alias",
            {"collectionName": "configured_collection"},
            FakeEmbedder(),
        )

        self.assertIs(result, new_collection)
        self.assertTrue(created)
        collection_factory.assert_called_once()
        self.assertEqual(
            collection_factory.call_args.args[0],
            "configured_collection",
        )
        self.assertIsNotNone(collection_factory.call_args.kwargs["schema"])
        new_collection.create_index.assert_called_once()

    def test_reads_all_collections_and_upserts_stable_vector_rows(self):
        mongo = FakeMongoDatabase({
            "api_documents": FakeMongoCollection([
                {
                    "_id": "record-1",
                    "payload": {"market": "पटना"},
                    "embedding": [9, 9, 9],
                },
            ]),
            "agriculture_documents": FakeMongoCollection([
                {"_id": "record-2", "content": "English text"},
            ]),
        })
        milvus = FakeMilvusCollection()
        indexer = MongoToMilvusIndexer(
            mongo,
            milvus,
            FakeEmbedder(),
            database_name="bihar_agriculture",
            batch_size=2,
        )

        result = indexer.run()

        self.assertEqual(result["mongo_collections"], 2)
        self.assertEqual(result["documents_read"], 2)
        self.assertEqual(result["vectors_upserted"], 2)
        self.assertEqual(result["milvus_collection"], "configured_collection")
        self.assertEqual(len(milvus.upserts), 2)
        self.assertTrue(milvus.upserts[0]["pk"])
        self.assertEqual(milvus.upserts[0]["embedding"], [0.1, 0.2, 0.3])
        self.assertEqual(
            milvus.upserts[0]["metadata"]["mongo_collection"],
            "api_documents",
        )
        self.assertNotIn('"embedding"', milvus.upserts[0]["text_content"])

    def test_chunks_text_by_utf8_byte_limit_without_losing_content(self):
        text = "कृषि data"
        chunks = _chunks_by_utf8_size(text, 8)

        self.assertEqual("".join(chunks), text)
        self.assertTrue(
            all(len(chunk.encode("utf-8")) <= 8 for chunk in chunks)
        )

    def test_rejects_embedding_dimension_mismatch(self):
        class BadEmbedder(FakeEmbedder):
            def embed_texts(self, texts):
                return [[0.1, 0.2] for _ in texts]

        indexer = MongoToMilvusIndexer(
            FakeMongoDatabase({
                "sample": FakeMongoCollection([{"_id": "one"}]),
            }),
            FakeMilvusCollection(),
            BadEmbedder(),
        )

        with self.assertRaisesRegex(ValueError, "does not match"):
            indexer.run()


if __name__ == "__main__":
    unittest.main()
