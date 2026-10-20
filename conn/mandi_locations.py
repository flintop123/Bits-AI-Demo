"""MongoDB persistence for verified mandi coordinates."""

import os
from datetime import datetime, timezone

from pymongo import ASCENDING, GEOSPHERE, MongoClient, UpdateOne

from services.market_geocoding_service import SOURCE_LICENSE


class MandiLocationMongo:
    IDENTITY_FIELDS = ("market_code",)

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
        self.collection = self.db["mandi_locations"]
        self._ensure_indexes()

    def _ensure_indexes(self):
        self.collection.create_index(
            [("market_code", ASCENDING)],
            unique=True,
            name="unique_mandi_market_code",
        )
        self.collection.create_index(
            [("location", GEOSPHERE)], name="mandi_location_2dsphere"
        )
        self.collection.create_index(
            [("district_code", ASCENDING), ("market_name", ASCENDING)],
            name="mandi_location_district",
        )

    def ping(self):
        return self.client.admin.command("ping")

    def upsert_verified(self, records):
        operations = []
        now = datetime.now(timezone.utc)
        for record in records:
            if record.get("verification_status") != "verified":
                raise ValueError("Only verified mandi locations may be stored")
            if record.get("location_precision") not in {
                "market_facility", "market_locality_centroid",
            }:
                raise ValueError("A supported location_precision is required")
            coordinates = record.get("location", {}).get("coordinates", [])
            if len(coordinates) != 2:
                raise ValueError("GeoJSON location requires two coordinates")
            stored = dict(record)
            stored.setdefault("geocoded_at", now)
            stored.setdefault("coordinate_source_license", SOURCE_LICENSE)
            operations.append(UpdateOne(
                {"market_code": stored["market_code"]},
                {"$set": stored, "$setOnInsert": {"created_at": now}},
                upsert=True,
            ))
        if not operations:
            return {"inserted": 0, "matched": 0, "modified": 0}
        result = self.collection.bulk_write(operations, ordered=False)
        return {
            "inserted": result.upserted_count,
            "matched": result.matched_count,
            "modified": result.modified_count,
        }

    def close(self):
        if self._owns_client:
            self.client.close()
