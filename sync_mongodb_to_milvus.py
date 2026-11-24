"""Build an explicitly approved public-document corpus in a new collection."""

import hashlib
import json
import os
import re
from itertools import islice
from urllib.parse import urlsplit

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


PUBLIC_COLLECTION = "agriculture_documents"
PUBLIC_FIELDS = {
    "_id": 1, "source_url": 1, "document_title": 1, "page_number": 1,
    "chunk_index": 1, "content": 1, "source_hash": 1,
}
COLLECTION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")


def milvus_settings(config):
    settings = config.get("milvus") or {}
    host, port = settings.get("host", "127.0.0.1"), settings.get("port", 19530)
    uri = os.getenv("AGRI_MILVUS_URI") or f"http://{host}:{port}"
    parsed = urlsplit(uri)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or (
        parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Invalid Milvus URI")
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not local and parsed.scheme != "https":
        raise ValueError("A remote Milvus URI must use HTTPS")
    token = os.getenv("AGRI_MILVUS_TOKEN")
    kwargs = {"uri": uri, "secure": parsed.scheme == "https"}
    if token:
        if not kwargs["secure"]:
            raise ValueError("Use HTTPS with a Milvus token")
        kwargs["token"] = token
    return kwargs, local


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
        approved_sources=(),
        max_documents=2000,
    ):
        if not 1 <= batch_size <= 32 or not 1 <= max_documents <= 10000:
            raise ValueError("Use batch size 1–32 and a document limit of 1–10,000")
        self.mongo_database = mongo_database
        self.milvus_collection = milvus_collection
        self.embedder = embedder or OllamaEmbeddingClient()
        self.database_name = database_name
        self.batch_size = batch_size
        self.approved_sources = tuple(approved_sources)
        self.max_documents = max_documents
        self.details = describe_milvus_collection(
            milvus_collection,
            field_config or {},
        )
        dimension = self.details["vector_field"].params.get("dim")
        self.vector_dimension = int(dimension) if dimension else None

    def run(self):
        if not self.approved_sources:
            raise ValueError("No reviewed public document sources configured")
        collection = self.mongo_database[PUBLIC_COLLECTION]
        selector = {"source_url": {"$in": list(self.approved_sources)}}
        if not 0 < collection.count_documents(selector, limit=self.max_documents + 1) <= self.max_documents:
            raise ValueError("No approved documents, or the reviewed document limit was exceeded")
        documents_read = 0
        vectors_upserted = 0
        with collection.find(selector, PUBLIC_FIELDS) as cursor:
            while True:
                batch = list(islice(cursor, self.batch_size))
                if not batch:
                    break
                documents_read += len(batch)
                if documents_read > self.max_documents:
                    raise ValueError("Source changed during indexing; discard the incomplete build")
                if any(doc.get("source_url") not in self.approved_sources for doc in batch):
                    raise ValueError("Unapproved source returned; discard the incomplete build")
                rows = self._prepare_rows(PUBLIC_COLLECTION, batch)
                if rows:
                    self._upsert_rows(rows)
                    vectors_upserted += len(rows)

        return {
            "database": self.database_name,
            "mongo_collections": 1,
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
        max_bytes = min(self.details["text_max_length"], 3000)
        for document in documents:
            mongo_id = document.get("_id")
            if mongo_id is None:
                raise ValueError(
                    f"MongoDB document in {collection_name} has no _id"
                )
            text = self._document_text(document)
            if not text:
                raise ValueError("Approved corpus contains a document without source text")
            if len(text.encode("utf-8")) > 30000:
                raise ValueError("Approved document is too large; extract reviewed page chunks first")
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
                    "part_index": chunk_index,
                    "page_number": document.get("page_number"),
                    "chunk_index": document.get("chunk_index"),
                    "source_hash": document.get("source_hash"),
                    "document_title": str(document.get("document_title", ""))[:300],
                    "embedding_model": self.embedder.model,
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
        content = document.get("content")
        return content.strip() if isinstance(content, str) else ""


def sync_mongodb_to_milvus(
    config,
    *,
    collection_name,
    write=False,
    allow_remote=False,
    max_documents=2000,
    mongo_client=None,
    embedder=None,
):
    ingestion_config = config.get("document_ingestion", {})
    if not COLLECTION_NAME.fullmatch(collection_name):
        raise ValueError("Use a Milvus collection name containing only letters, digits and underscores")
    approved_sources = ingestion_config.get("approved_document_sources", ())
    if not isinstance(approved_sources, (list, tuple)) or len(approved_sources) > 100:
        raise ValueError("Use a list of up to 100 exact reviewed public HTTPS source URLs")
    for source in approved_sources:
        parsed = urlsplit(source)
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or len(source) > 2048
        ):
            raise ValueError("Approved sources must be exact public HTTPS URLs without credentials or query tokens")
    if not 1 <= max_documents <= 10000:
        raise ValueError("Document limit must be between 1 and 10,000")
    database_name = ingestion_config.get(
        "mongo_database",
        config.get("mongodb", {}).get("database", "bihar_agriculture"),
    )
    batch_size = int(ingestion_config.get("milvus_batch_size", 16))
    if not 1 <= batch_size <= 32:
        raise ValueError("Milvus batch size must be between 1 and 32")
    plan = {
        "database": database_name, "mongo_collection": PUBLIC_COLLECTION,
        "milvus_collection": collection_name, "approved_sources": list(approved_sources),
        "max_documents": max_documents, "replace_existing": False,
    }
    if not write:
        return {**plan, "mode": "plan_only", "saved": False}
    if not approved_sources:
        raise ValueError("Configure reviewed public sources before enabling writes")
    connection_options, local = milvus_settings(config)
    if not local and not allow_remote:
        raise ValueError("Remote indexing requires a separately confirmed --allow-remote")
    owns_mongo_client = mongo_client is None
    connected_milvus = False
    alias = "mongo_milvus_build"
    embedder = embedder or OllamaEmbeddingClient()

    try:
        if mongo_client is None:
            mongo_uri = os.getenv(
                "MONGODB_URI",
                config.get("mongodb", {}).get(
                    "uri", "mongodb://localhost:27017/"
                ),
            )
            mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            mongo_client.admin.command("ping")
        mongo_database = mongo_client[database_name]

        connections.connect(alias=alias, timeout=10, **connection_options)
        connected_milvus = True
        milvus_collection, created = _get_or_create_milvus_collection(
            collection_name, alias, {"collectionName": collection_name}, embedder,
        )
        if not created:
            raise ValueError("Build requires a new collection name; existing data was not touched")

        indexer = MongoToMilvusIndexer(
            mongo_database,
            milvus_collection,
            embedder,
            database_name=database_name,
            batch_size=batch_size,
            approved_sources=approved_sources,
            max_documents=max_documents,
        )
        summary = indexer.run()
        milvus_collection.flush(timeout=60)
        milvus_collection.load(timeout=60)
        utility.wait_for_loading_complete(collection_name, using=alias, timeout=60)
        return {**plan, **summary, "saved": True, "mode": "new_corpus",
                "activated": False, "ready_for_review": True}
    finally:
        if connected_milvus:
            connections.disconnect(alias)
        if owns_mongo_client and mongo_client is not None:
            mongo_client.close()
