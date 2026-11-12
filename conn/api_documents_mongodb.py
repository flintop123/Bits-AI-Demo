"""MongoDB persistence for generic API response records."""

import hashlib
import json
import os
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne


class ApiDocumentsMongo:
    def __init__(self, uri=None, database=None):
        if database is None:
            uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
            self.client = MongoClient(uri)
            self.db = self.client["bihar_agriculture"]
            self._owns_client = True
        else:
            self.db = database
            self.client = getattr(database, "client", None)
            self._owns_client = False
        self.collection = self.db["api_documents"]
        self.collection.create_index(
            [("source_url", 1), ("record_hash", 1)],
            unique=True,
            name="unique_api_source_record",
        )

    def upsert_records(self, source_url, response_kind, records):
        if not records:
            return {"inserted": 0, "matched": 0, "modified": 0}

        received_at = datetime.now(timezone.utc)
        operations = []
        seen_hashes = set()
        for record in records:
            serialized = json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            record_hash = hashlib.sha256(
                serialized.encode("utf-8")
            ).hexdigest()
            if record_hash in seen_hashes:
                continue
            seen_hashes.add(record_hash)
            operations.append(
                UpdateOne(
                    {
                        "source_url": source_url,
                        "record_hash": record_hash,
                    },
                    {
                        "$setOnInsert": {
                            "source_url": source_url,
                            "response_kind": response_kind,
                            "record_hash": record_hash,
                            "payload": record,
                            "received_at": received_at,
                        }
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

    def close(self):
        if self._owns_client:
            self.client.close()
