"""MongoDB persistence for page-aware agriculture document chunks."""

import os
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne


class AgricultureDocumentsMongo:
    IDENTITY_FIELDS = ("source_url", "page_number", "chunk_index")

    def __init__(self, uri=None):
        uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        self.client = MongoClient(uri)
        self.db = self.client["bihar_agriculture"]
        self.collection = self.db["agriculture_documents"]
        self.collection.create_index(
            [(field, 1) for field in self.IDENTITY_FIELDS],
            unique=True,
            name="unique_document_page_chunk",
        )
        self._ensure_multilingual_text_index()

    def _ensure_multilingual_text_index(self):
        """Create one language-neutral text index for English and Hindi."""
        index_name = "agriculture_document_text"
        language_override = "text_search_language"
        existing = self.collection.index_information().get(index_name)
        if existing and (
            existing.get("default_language") != "none"
            or existing.get("language_override", "language")
            != language_override
        ):
            self.collection.drop_index(index_name)
        self.collection.create_index(
            [("content", "text"), ("document_title", "text")],
            name=index_name,
            default_language="none",
            language_override=language_override,
        )

    def upsert_records(self, records):
        if not records:
            return {"inserted": 0, "matched": 0, "modified": 0}

        ingested_at = datetime.now(timezone.utc)
        operations = []
        for record in records:
            stored_record = dict(record)
            identity = {
                field: stored_record[field]
                for field in self.IDENTITY_FIELDS
            }
            operations.append(
                UpdateOne(
                    identity,
                    {
                        "$set": stored_record,
                        "$setOnInsert": {"ingested_at": ingested_at},
                    },
                    upsert=True,
                )
            )

        result = self.collection.bulk_write(operations, ordered=False)
        return {
            "inserted": result.upserted_count,
            "matched": result.matched_count,
            "modified": result.modified_count,
        }
