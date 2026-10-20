"""MongoDB persistence for normalized crop statistics."""

import os
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne


class CropStatisticsMongo:
    IDENTITY_FIELDS = ("crop", "season", "year")

    def __init__(self, uri=None):
        uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        self.client = MongoClient(uri)
        self.db = self.client["bihar_agriculture"]
        self.collection = self.db["crop_statistics"]
        self.collection.create_index(
            [(field, 1) for field in self.IDENTITY_FIELDS],
            unique=True,
            name="unique_crop_season_year",
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
