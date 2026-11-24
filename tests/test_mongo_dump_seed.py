import unittest
from unittest.mock import MagicMock, patch

from db import load_dump


class MongoDumpSeedTests(unittest.TestCase):
    def setUp(self):
        self.records = {name: [{"label": name}] for name in load_dump.COLLECTIONS}
        self.collections = {name: MagicMock() for name in load_dump.COLLECTIONS}
        self.database = MagicMock()
        self.database.list_collection_names.return_value = []
        self.database.__getitem__.side_effect = self.collections.__getitem__
        for collection in self.collections.values():
            collection.find_one.return_value = None
            collection.count_documents.return_value = 1

    def test_existing_documents_abort_before_any_modification(self):
        self.collections["mandi_prices"].find_one.return_value = {"_id": 1}
        with self.assertRaisesRegex(ValueError, "existing records in mandi_prices"):
            load_dump.seed_mongo(self.records, self.database)
        for collection in self.collections.values():
            collection.create_index.assert_not_called()
            collection.insert_many.assert_not_called()

    def test_seed_creates_read_side_indexes_and_preserves_records(self):
        counts = load_dump.seed_mongo(self.records, self.database)
        self.assertEqual(counts, dict.fromkeys(load_dump.COLLECTIONS, 1))
        self.collections["mandi_locations"].create_index.assert_called_once_with(
            [("location", "2dsphere")], name="mandi_location_2dsphere"
        )
        self.assertEqual(self.collections["agriculture_documents"].create_index
                         .call_args.kwargs["default_language"], "none")
        for name, collection in self.collections.items():
            collection.insert_many.assert_called_once_with(self.records[name])
            self.assertIsNot(collection.insert_many.call_args.args[0][0], self.records[name][0])

    def test_validation_mode_never_calls_mongo_or_sqlite(self):
        with patch.object(load_dump, "read_collection", return_value=[]), \
                patch.object(load_dump, "seed_mongo") as mongo, \
                patch.object(load_dump, "load_sqlite") as sqlite:
            self.assertEqual(load_dump.main(["--validate-only"]), 0)
        mongo.assert_not_called()
        sqlite.assert_not_called()
