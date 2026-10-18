"""Read-only MongoDB queries for agriculture data."""

import os
import re

from pymongo import MongoClient

from services.ollama_embedding_client import (
    OllamaEmbeddingClient,
    OllamaEmbeddingUnavailableError,
)


class AgricultureQueryService:
    DOCUMENT_FIELDS = {
        "_id": 0,
        "document_title": 1,
        "page_number": 1,
        "chunk_index": 1,
        "content": 1,
        "content_hash": 1,
        "source_url": 1,
        "source_file": 1,
        "source_id": 1,
        "source_organization": 1,
        "language": 1,
        "declared_language": 1,
        "extraction_method": 1,
    }

    def __init__(self, database=None, uri=None, embedding_client=None):
        if database is None:
            uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
            self.client = MongoClient(uri)
            self.database = self.client["bihar_agriculture"]
            self._owns_client = True
        else:
            self.database = database
            self.client = database.client
            self._owns_client = False

        self.mandi_prices = self.database["mandi_prices"]
        self.crop_statistics = self.database["crop_statistics"]
        self.agriculture_documents = self.database["agriculture_documents"]
        self._embedding_client = embedding_client

    def health(self):
        self.client.admin.command("ping")
        return {
            "status": "ok",
            "database": "bihar_agriculture",
            "collections": {
                "mandi_prices": self.mandi_prices.count_documents({}),
                "crop_statistics": self.crop_statistics.count_documents({}),
                "agriculture_documents": (
                    self.agriculture_documents.count_documents({})
                ),
                "document_embeddings": (
                    self.agriculture_documents.count_documents({
                        "embedding": {"$exists": True, "$ne": []},
                    })
                ),
            },
        }

    def find_mandi_prices(self, filters, limit):
        query = {}
        for field in ("district", "market", "crop", "variety"):
            value = filters.get(field)
            if value:
                query[field] = self._exact_text(value)
        if filters.get("date"):
            query["date"] = filters["date"]

        cursor = self.mandi_prices.find(query, {"_id": 0})
        cursor = cursor.sort([("date", -1), ("district", 1), ("crop", 1)])
        return list(cursor.limit(limit))

    def find_crop_statistics(self, filters, limit):
        query = {}
        for field in ("crop", "season"):
            value = filters.get(field)
            if value:
                query[field] = self._exact_text(value)
        if filters.get("year"):
            query["year"] = filters["year"]

        cursor = self.crop_statistics.find(query, {"_id": 0})
        cursor = cursor.sort([("year", -1), ("crop", 1), ("season", 1)])
        return list(cursor.limit(limit))

    def search_agriculture_documents(
        self, search_terms, limit, semantic_query=None
    ):
        search_terms = str(search_terms or "").strip()
        if not search_terms:
            raise ValueError("search terms are required")
        if len(search_terms) > 200:
            raise ValueError("search terms must not exceed 200 characters")
        semantic_query = (
            str(semantic_query).strip()
            if semantic_query is not None else None
        )
        if semantic_query is not None and not semantic_query:
            raise ValueError("semantic query must not be blank")
        if semantic_query is not None and len(semantic_query) > 500:
            raise ValueError("semantic query must not exceed 500 characters")

        candidate_limit = max(20, min(100, limit * 8))
        keyword_records = self._keyword_document_search(
            search_terms, candidate_limit
        )
        semantic_records = []
        semantic_warning = None
        if semantic_query is not None:
            try:
                semantic_records = self._semantic_document_search(
                    semantic_query, candidate_limit
                )
            except OllamaEmbeddingUnavailableError as exc:
                semantic_warning = str(exc)
        return self._fuse_document_results(
            keyword_records,
            semantic_records,
            limit,
            semantic_warning=semantic_warning,
        )

    def _keyword_document_search(self, search_terms, limit):
        projection = dict(self.DOCUMENT_FIELDS)
        projection["score"] = {"$meta": "textScore"}
        cursor = self.agriculture_documents.find(
            {"$text": {"$search": search_terms}},
            projection,
        )
        cursor = cursor.sort([("score", {"$meta": "textScore"})])
        return list(cursor.limit(limit))

    def _semantic_document_search(self, query, limit):
        embedding_client = (
            self._embedding_client or OllamaEmbeddingClient()
        )
        self._embedding_client = embedding_client
        query_vector = embedding_client.embed_query(query)
        projection = dict(self.DOCUMENT_FIELDS)
        projection.update({
            "embedding": 1,
            "embedding_model": 1,
            "embedding_content_hash": 1,
        })
        records = self.agriculture_documents.find(
            {"embedding_model": embedding_client.model}, projection
        )
        ranked = []
        for record in records:
            vector = record.pop("embedding", None)
            model = record.pop("embedding_model", None)
            embedded_hash = record.pop("embedding_content_hash", None)
            if (
                not isinstance(vector, list)
                or len(vector) != len(query_vector)
                or embedded_hash != record.get("content_hash")
            ):
                continue
            similarity = sum(
                left * right for left, right in zip(query_vector, vector)
            )
            record["semantic_similarity"] = round(similarity, 8)
            record["embedding_model"] = model
            ranked.append(record)
        ranked.sort(
            key=lambda item: item["semantic_similarity"], reverse=True
        )
        return ranked[:limit]

    @classmethod
    def _fuse_document_results(
        cls,
        keyword_records,
        semantic_records,
        limit,
        *,
        semantic_warning=None,
        rrf_constant=60,
    ):
        fused = {}

        def add(records, method, weight):
            for rank, record in enumerate(records, start=1):
                identity = cls._document_identity(record)
                entry = fused.setdefault(identity, {
                    "record": dict(record),
                    "score": 0.0,
                    "methods": [],
                    "keyword_rank": None,
                    "semantic_rank": None,
                })
                entry["score"] += weight / (rrf_constant + rank)
                entry["methods"].append(method)
                entry[f"{method}_rank"] = rank
                if method == "semantic":
                    entry["record"]["semantic_similarity"] = record.get(
                        "semantic_similarity"
                    )
                    if record.get("embedding_model"):
                        entry["record"]["embedding_model"] = record[
                            "embedding_model"
                        ]

        add(keyword_records, "keyword", 1.0)
        add(semantic_records, "semantic", 1.0)
        ordered = sorted(
            fused.values(),
            key=lambda item: (
                item["score"],
                item["record"].get("semantic_similarity", -1),
            ),
            reverse=True,
        )
        output = []
        for item in ordered[:limit]:
            record = item["record"]
            methods = sorted(set(item["methods"]))
            record["retrieval"] = {
                "mode": (
                    "hybrid" if len(methods) == 2 else methods[0]
                ),
                "methods": methods,
                "hybrid_score": round(item["score"], 8),
                "keyword_rank": item["keyword_rank"],
                "semantic_rank": item["semantic_rank"],
            }
            if semantic_warning:
                record["retrieval"]["semantic_warning"] = semantic_warning
            output.append(record)
        return output

    @staticmethod
    def _document_identity(record):
        return (
            record.get("source_url"),
            record.get("page_number"),
            record.get("chunk_index"),
        )

    def list_values(self):
        return {
            "mandi_crops": sorted(self.mandi_prices.distinct("crop")),
            "districts": sorted(self.mandi_prices.distinct("district")),
            "statistical_crops": sorted(
                self.crop_statistics.distinct("crop")
            ),
            "seasons": sorted(self.crop_statistics.distinct("season")),
        }

    def close(self):
        """Close only a Mongo client created by this service."""
        if self._owns_client:
            self.client.close()

    @staticmethod
    def _exact_text(value):
        return {
            "$regex": f"^{re.escape(value.strip())}$",
            "$options": "i",
        }
