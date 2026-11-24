"""MongoDB persistence for evidence-anchored semantic agriculture facts."""

import os
from datetime import datetime, timezone

from pymongo import ASCENDING, MongoClient, UpdateOne


class AgricultureFactsMongo:
    IDENTITY_FIELDS = ("fact_id",)

    def __init__(self, uri=None):
        uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        self.client = MongoClient(uri)
        self.db = self.client["bihar_agriculture"]
        self.collection = self.db["agriculture_facts"]
        self.collection.create_index(
            [("fact_id", ASCENDING)],
            unique=True,
            name="unique_semantic_agriculture_fact",
        )
        self.collection.create_index(
            [
                ("source_hash", ASCENDING),
                ("page_number", ASCENDING),
                ("chunk_index", ASCENDING),
            ],
            name="semantic_fact_source_locator",
        )
        self.collection.create_index(
            [
                ("fact_type", ASCENDING),
                ("crop", ASCENDING),
                ("period", ASCENDING),
                ("geography", ASCENDING),
            ],
            name="semantic_fact_dimensions",
        )

    def upsert_records(self, records):
        if not records:
            return {"inserted": 0, "matched": 0, "modified": 0}
        ingested_at = datetime.now(timezone.utc)
        operations = []
        for record in records:
            stored = dict(record)
            operations.append(UpdateOne(
                {"fact_id": stored["fact_id"]},
                {
                    "$set": stored,
                    "$setOnInsert": {"ingested_at": ingested_at},
                },
                upsert=True,
            ))
        result = self.collection.bulk_write(operations, ordered=False)
        return {
            "inserted": result.upserted_count,
            "matched": result.matched_count,
            "modified": result.modified_count,
        }
