"""Synchronize every document in a MongoDB database to a Milvus collection."""

import hashlib
import json
import os
from itertools import islice

from bson import json_util
from pymongo import MongoClient
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from services.ollama_embedding_client import OllamaEmbeddingClient


def describe_milvus_collection(collection, config):
    schema = collection.schema
    fields = {field.name: field for field in schema.fields}
    primary = next(
        (field for field in schema.fields if field.is_primary),
        None,
    )
    if primary is None:
        raise ValueError("Milvus collection has no primary-key field")
    if getattr(primary, "auto_id", getattr(schema, "auto_id", False)):
        raise ValueError(
            "Milvus collection uses auto-generated primary keys; stable "
            "MongoDB upserts require a non-auto primary key"
        )

    vector_name = config.get("vectorField")
    vector_field = fields.get(vector_name) if vector_name else None
    if vector_field is None:
        vector_field = next(
            (
                fields[name]
                for name in ("embedding", "vector")
                if name in fields
                and fields[name].dtype == DataType.FLOAT_VECTOR
            ),
            None,
        )
    if vector_field is None:
        vector_field = next(
            (
                field for field in schema.fields
                if field.dtype == DataType.FLOAT_VECTOR
            ),
            None,
        )
    if vector_field is None:
        raise ValueError(
            "Milvus collection must contain a dense FLOAT_VECTOR field"
        )

    text_name = config.get("textField")
    text_field = fields.get(text_name) if text_name else None
    if text_field is None:
        text_field = next(
            (
                fields[name]
                for name in ("text_content", "text", "content")
                if name in fields
                and fields[name].dtype == DataType.VARCHAR
                and name != primary.name
            ),
            None,
        )
    if text_field is None:
        text_field = next(
            (
                field for field in schema.fields
                if field.dtype == DataType.VARCHAR
                and field.name != primary.name
            ),
            None,
        )
    if text_field is None:
        raise ValueError(
            "Milvus collection must contain a VARCHAR text field"
        )

    metadata_name = config.get("metadataField", "metadata")
    metadata_field = fields.get(metadata_name)
    if metadata_field and metadata_field.dtype not in {
        DataType.JSON,
        DataType.VARCHAR,
    }:
        metadata_field = None
    source_name = config.get("sourceField", "source")
    source_field = fields.get(source_name)
    if source_field and source_field.dtype != DataType.VARCHAR:
        source_field = None

    primary_type = primary.dtype
    if primary_type not in {DataType.VARCHAR, DataType.INT64}:
        raise ValueError(
            "Milvus primary key must be VARCHAR or INT64 for MongoDB sync"
        )

    text_max_length = int(text_field.params.get("max_length", 8192))
    if text_max_length < 1:
        raise ValueError("Milvus text field max_length must be positive")
    primary_max_length = int(primary.params.get("max_length", 0))
    if primary_type == DataType.VARCHAR and primary_max_length < 16:
        raise ValueError(
            "Milvus VARCHAR primary key must allow at least 16 characters"
        )

    return {
        "collection_name": collection.name,
        "fields": [
            {
                "name": field.name,
                "type": getattr(field.dtype, "name", str(field.dtype)),
                "params": dict(field.params),
                "primary": field.is_primary,
            }
            for field in schema.fields
        ],
        "primary_field": primary,
        "vector_field": vector_field,
        "text_field": text_field,
        "metadata_field": metadata_field,
        "source_field": source_field,
        "dynamic_fields": bool(
            getattr(schema, "enable_dynamic_field", False)
        ),
        "text_max_length": text_max_length,
        "primary_max_length": primary_max_length,
    }


def _chunks_by_utf8_size(text, max_bytes):
    chunks = []
    current = []
    current_size = 0
    for character in text:
        size = len(character.encode("utf-8"))
        if current and current_size + size > max_bytes:
            chunks.append("".join(current))
            current = []
            current_size = 0
        current.append(character)
        current_size += size
    if current:
        chunks.append("".join(current))
    return chunks


def _build_collection_schema(config, embedder):
    collection_name = config.get("collectionName")
    if not collection_name:
        raise ValueError("Set milvus.collectionName in config.yaml")
    dimension = len(embedder.embed_query("MongoDB document dimension check"))
    if dimension < 1:
        raise ValueError("Embedding model returned an empty vector")

    primary_name = config.get("primaryField", "pk")
    text_name = config.get("textField", "text_content")
    vector_name = config.get("vectorField", "embedding")
    source_name = config.get("sourceField", "source")
    metadata_name = config.get("metadataField", "metadata")
    fields = [
        FieldSchema(
            name=primary_name,
            dtype=DataType.VARCHAR,
            is_primary=True,
            auto_id=False,
            max_length=64,
        ),
        FieldSchema(
            name=text_name,
            dtype=DataType.VARCHAR,
            max_length=65535,
        ),
        FieldSchema(
            name=vector_name,
            dtype=DataType.FLOAT_VECTOR,
            dim=dimension,
        ),
        FieldSchema(
            name=source_name,
            dtype=DataType.VARCHAR,
            max_length=2048,
        ),
        FieldSchema(name=metadata_name, dtype=DataType.JSON),
    ]
    return CollectionSchema(
        fields=fields,
        description=f"MongoDB documents indexed from {collection_name}",
    )


def _get_or_create_milvus_collection(
    collection_name,
    alias,
    config,
    embedder,
):
    if utility.has_collection(collection_name, using=alias):
        return Collection(collection_name, using=alias), False

    schema = _build_collection_schema(config, embedder)
    collection = Collection(
        collection_name,
        schema=schema,
        using=alias,
    )
    vector_name = config.get("vectorField", "embedding")
    collection.create_index(
        vector_name,
        {
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
        },
    )
    return collection, True


class MongoToMilvusIndexer:
    def __init__(
        self,
        mongo_database,
        milvus_collection,
        embedder=None,
        *,
        database_name="bihar_agriculture",
        batch_size=16,
        field_config=None,
    ):
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.mongo_database = mongo_database
        self.milvus_collection = milvus_collection
        self.embedder = embedder or OllamaEmbeddingClient()
        self.database_name = database_name
        self.batch_size = batch_size
        self.details = describe_milvus_collection(
            milvus_collection,
            field_config or {},
        )
        dimension = self.details["vector_field"].params.get("dim")
        self.vector_dimension = int(dimension) if dimension else None

    def run(self):
        collection_names = self.mongo_database.list_collection_names()
        documents_read = 0
        vectors_upserted = 0
        for collection_name in collection_names:
            source_collection = self.mongo_database[collection_name]
            cursor = iter(source_collection.find({}))
            while True:
                batch = list(islice(cursor, self.batch_size))
                if not batch:
                    break
                documents_read += len(batch)
                rows = self._prepare_rows(collection_name, batch)
                if rows:
                    self._upsert_rows(rows)
                    vectors_upserted += len(rows)

        return {
            "database": self.database_name,
            "mongo_collections": len(collection_names),
            "documents_read": documents_read,
            "vectors_upserted": vectors_upserted,
            "embedding_model": self.embedder.model,
            "milvus_collection": self.details["collection_name"],
            "milvus_primary_field":
                self.details["primary_field"].name,
            "milvus_text_field": self.details["text_field"].name,
            "milvus_vector_field": self.details["vector_field"].name,
            "milvus_fields": [
                field["name"] for field in self.details["fields"]
            ],
        }

    def _prepare_rows(self, collection_name, documents):
        pending = []
        rows = []
        max_bytes = min(self.details["text_max_length"], 8192)
        for document in documents:
            mongo_id = document.get("_id")
            if mongo_id is None:
                raise ValueError(
                    f"MongoDB document in {collection_name} has no _id"
                )
            text = self._document_text(document)
            chunks = _chunks_by_utf8_size(text, max_bytes)
            for chunk_index, chunk in enumerate(chunks):
                source_id = (
                    f"{self.database_name}.{collection_name}:"
                    f"{mongo_id}:{chunk_index}"
                )
                metadata = {
                    "mongo_database": self.database_name,
                    "mongo_collection": collection_name,
                    "mongo_id": str(mongo_id),
                    "chunk_index": chunk_index,
                }
                source = (
                    document.get("source_url")
                    or document.get("source")
                    or source_id
                )
                pending.append((source_id, chunk, metadata, str(source)))

        for start in range(0, len(pending), self.batch_size):
            batch = pending[start:start + self.batch_size]
            texts = [item[1] for item in batch]
            vectors = self.embedder.embed_texts(texts)
            if len(vectors) != len(batch):
                raise ValueError(
                    "Embedding service returned a different number of "
                    "vectors than input texts"
                )
            for (source_id, text, metadata, source), vector in zip(
                batch, vectors
            ):
                if self.vector_dimension and (
                    len(vector) != self.vector_dimension
                ):
                    raise ValueError(
                        f"Embedding dimension {len(vector)} does not match "
                        f"Milvus field dimension {self.vector_dimension}"
                    )
                row = {
                    self.details["primary_field"].name:
                        self._milvus_primary_key(source_id),
                    self.details["text_field"].name: text,
                    self.details["vector_field"].name: vector,
                }
                metadata_field = self.details["metadata_field"]
                if metadata_field:
                    row[metadata_field.name] = (
                        metadata
                        if metadata_field.dtype == DataType.JSON
                        else json.dumps(metadata, ensure_ascii=False)
                    )
                elif self.details["dynamic_fields"]:
                    row["metadata"] = metadata

                source_field = self.details["source_field"]
                if source_field:
                    row[source_field.name] = source
                elif self.details["dynamic_fields"]:
                    row["source"] = source
                rows.append(row)
        return rows

    def _upsert_rows(self, rows):
        for start in range(0, len(rows), self.batch_size):
            self.milvus_collection.upsert(
                rows[start:start + self.batch_size]
            )

    def _milvus_primary_key(self, source_id):
        primary = self.details["primary_field"]
        digest = hashlib.sha256(source_id.encode("utf-8")).digest()
        if primary.dtype == DataType.INT64:
            return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
        max_length = self.details["primary_max_length"]
        return digest.hex()[:max_length]

    @staticmethod
    def _document_text(document):
        content = {
            key: value
            for key, value in document.items()
            if key not in {
                "embedding",
                "embedding_model",
                "embedding_dimension",
                "embedding_content_hash",
                "embedded_at",
            }
        }
        return json_util.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
        )


def sync_mongodb_to_milvus(
    config,
    *,
    mongo_client=None,
    milvus_collection=None,
    embedder=None,
):
    ingestion_config = config.get("document_ingestion", {})
    milvus_config = config.get("milvus") or {}
    database_name = ingestion_config.get(
        "mongo_database",
        config.get("mongodb", {}).get("database", "bihar_agriculture"),
    )
    batch_size = int(ingestion_config.get("milvus_batch_size", 16))
    owns_mongo_client = mongo_client is None
    connected_milvus = False
    alias = "mongo_milvus_sync"
    collection_created = False
    embedder = embedder or OllamaEmbeddingClient()

    try:
        if mongo_client is None:
            mongo_uri = os.getenv(
                "MONGODB_URI",
                config.get("mongodb", {}).get(
                    "uri", "mongodb://localhost:27017/"
                ),
            )
            mongo_client = MongoClient(mongo_uri)
            mongo_client.admin.command("ping")
        mongo_database = mongo_client[database_name]

        if milvus_collection is None:
            collection_name = milvus_config.get("collectionName")
            uri = milvus_config.get("zilliz_uri")
            if not uri:
                host = milvus_config.get("host")
                port = milvus_config.get("port")
                if not host or not port:
                    raise ValueError(
                        "Set milvus.zilliz_uri or milvus.host and "
                        "milvus.port in config.yaml"
                    )
                uri = f"http://{host}:{port}"
            if not collection_name:
                raise ValueError(
                    "Set milvus.collectionName in config.yaml"
                )

            connection_options = {
                "alias": alias,
                "uri": uri,
                "secure": uri.lower().startswith("https://"),
            }
            token = milvus_config.get("zilliz_token")
            if token:
                connection_options["token"] = token
            connections.connect(**connection_options)
            connected_milvus = True
            milvus_collection, collection_created = (
                _get_or_create_milvus_collection(
                    collection_name,
                    alias,
                    milvus_config,
                    embedder,
                )
            )

        indexer = MongoToMilvusIndexer(
            mongo_database,
            milvus_collection,
            embedder,
            database_name=database_name,
            batch_size=batch_size,
            field_config=milvus_config,
        )
        summary = indexer.run()
        summary["milvus_collection_created"] = collection_created
        return summary
    finally:
        if connected_milvus:
            connections.disconnect(alias)
        if owns_mongo_client and mongo_client is not None:
            mongo_client.close()
