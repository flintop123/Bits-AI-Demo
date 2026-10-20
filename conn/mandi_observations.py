"""MongoDB persistence for official daily mandi observations and runs."""

import os
from copy import deepcopy
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient, UpdateOne


OFFICIAL_IDENTITY_FIELDS = ("source_record_id", "date")
LEGACY_IDENTITY_FIELDS = (
    "district",
    "market",
    "date",
    "crop",
    "variety",
    "source_url",
)
LEGACY_INDEX_FIELDS = LEGACY_IDENTITY_FIELDS + ("source_record_id",)


def ensure_mandi_identity_indexes(collection):
    """Migrate mixed browser/API identities without collapsing API rows."""
    indexes = collection.index_information()
    old_official = "unique_mandi_source_record_id"
    if old_official in indexes:
        collection.drop_index(old_official)

    expected_legacy = [
        (field, ASCENDING) for field in LEGACY_INDEX_FIELDS
    ]
    existing_legacy = indexes.get("unique_mandi_record")
    if existing_legacy and (
        existing_legacy.get("key") != expected_legacy
        or not existing_legacy.get("unique")
    ):
        collection.drop_index("unique_mandi_record")

    collection.create_index(
        expected_legacy,
        unique=True,
        name="unique_mandi_record",
    )
    collection.create_index(
        [("source_record_id", ASCENDING), ("date", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "source_record_id": {"$type": "string"}
        },
        name="unique_mandi_source_record_day",
    )


class MandiObservationMongo:
    OFFICIAL_IDENTITY_FIELDS = OFFICIAL_IDENTITY_FIELDS
    LEGACY_IDENTITY_FIELDS = LEGACY_IDENTITY_FIELDS

    def __init__(self, uri=None, database=None):
        if database is None:
            uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
            self.client = MongoClient(uri)
            self.db = self.client["bihar_agriculture"]
            self._owns_client = True
        else:
            self.db = database
            self.client = database.client
            self._owns_client = False
        self.collection = self.db["mandi_prices"]
        self.runs = self.db["mandi_ingestion_runs"]
        self._ensure_indexes()

    def _ensure_indexes(self):
        ensure_mandi_identity_indexes(self.collection)
        self.collection.create_index(
            [("date", DESCENDING)], name="mandi_date_desc"
        )
        self.collection.create_index(
            [
                ("district_code", ASCENDING),
                ("market_code", ASCENDING),
                ("crop_code", ASCENDING),
                ("date", DESCENDING),
            ],
            name="mandi_locality_time",
        )
        self.runs.create_index("run_id", unique=True)
        self.runs.create_index([("started_at", DESCENDING)])
        self.runs.create_index(
            [("collection_dates", ASCENDING), ("status", ASCENDING)]
        )

    def ping(self):
        return self.client.admin.command("ping")

    def upsert_records(self, records):
        if not records:
            return {"inserted": 0, "matched": 0, "modified": 0}
        operations = []
        for record in records:
            source_id = record.get("source_record_id")
            if not source_id:
                raise ValueError("source_record_id is required")
            official = {
                field: record[field]
                for field in self.OFFICIAL_IDENTITY_FIELDS
            }
            legacy = {
                field: record[field] for field in self.LEGACY_IDENTITY_FIELDS
            }
            legacy["source_record_id"] = {"$exists": False}
            operations.append(UpdateOne(
                {
                    "$or": [
                        official,
                        legacy,
                    ]
                },
                {"$set": record},
                upsert=True,
            ))
        result = self.collection.bulk_write(operations, ordered=False)
        return {
            "inserted": result.upserted_count,
            "matched": result.matched_count,
            "modified": result.modified_count,
        }

    def start_run(self, run):
        self.ping()
        self.runs.insert_one(deepcopy(run))

    def finish_run(self, run_id, updates):
        self.runs.update_one(
            {"run_id": run_id}, {"$set": deepcopy(updates)}
        )

    def get_run(self, run_id):
        return self.runs.find_one({"run_id": run_id}, {"_id": 0})

    def close(self):
        if self._owns_client:
            self.client.close()


def utc_now():
    return datetime.now(timezone.utc).isoformat()
