import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

from pymongo import ASCENDING

from conn.mandi_observations import (
    LEGACY_INDEX_FIELDS,
    MandiObservationMongo,
    ensure_mandi_identity_indexes,
)


def record(source_id, selected_date):
    return {
        "source_record_id": source_id,
        "district": "नालन्दा",
        "market": "हरनौत (नया)",
        "date": selected_date,
        "crop": "बैंगन",
        "variety": "Round",
        "source_url": "https://www.biharkrishi.in/mandi",
    }


class MandiObservationMongoTests(unittest.TestCase):
    def test_official_identity_includes_date(self):
        database = MandiObservationMongo.__new__(MandiObservationMongo)
        database.collection = Mock()
        database.collection.bulk_write.return_value = SimpleNamespace(
            upserted_count=2,
            matched_count=0,
            modified_count=0,
        )

        database.upsert_records([
            record("reused-id", "2026-10-17"),
            record("reused-id", "2026-10-18"),
        ])

        operations = database.collection.bulk_write.call_args.args[0]
        self.assertEqual(
            operations[0]._filter["$or"][0],
            {"source_record_id": "reused-id", "date": "2026-10-17"},
        )
        self.assertEqual(
            operations[1]._filter["$or"][0],
            {"source_record_id": "reused-id", "date": "2026-10-18"},
        )
        self.assertEqual(
            operations[0]._filter["$or"][1]["source_record_id"],
            {"$exists": False},
        )

    def test_legacy_indexes_are_migrated(self):
        collection = Mock()
        collection.index_information.return_value = {
            "unique_mandi_source_record_id": {},
            "unique_mandi_record": {
                "key": [
                    (field, ASCENDING)
                    for field in MandiObservationMongo.LEGACY_IDENTITY_FIELDS
                ],
                "unique": True,
            },
        }

        ensure_mandi_identity_indexes(collection)

        collection.drop_index.assert_has_calls([
            call("unique_mandi_source_record_id"),
            call("unique_mandi_record"),
        ])
        collection.create_index.assert_any_call(
            [(field, ASCENDING) for field in LEGACY_INDEX_FIELDS],
            unique=True,
            name="unique_mandi_record",
        )
        collection.create_index.assert_any_call(
            [
                ("source_record_id", ASCENDING),
                ("date", ASCENDING),
            ],
            unique=True,
            partialFilterExpression={
                "source_record_id": {"$type": "string"}
            },
            name="unique_mandi_source_record_day",
        )


if __name__ == "__main__":
    unittest.main()
