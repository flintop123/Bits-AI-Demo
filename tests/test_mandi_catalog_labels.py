import unittest

from conn.mandi_catalog_labels import MandiCatalogLabelMongo


class FakeBulkResult:
    pass


class FakeCollection:
    def __init__(self):
        self.documents = {}
        self.indexes = []

    def create_index(self, keys, **kwargs):
        self.indexes.append((keys, kwargs))

    def find(self, query, projection=None):
        values = set(query["official_value"]["$in"])
        return [
            dict(document)
            for key, document in self.documents.items()
            if key[0] == query["entity_type"] and key[1] in values
        ]

    def bulk_write(self, operations, ordered=False):
        for operation in operations:
            key = (
                operation._filter["entity_type"],
                operation._filter["official_value"],
            )
            self.documents[key] = dict(operation._doc["$set"])
        return FakeBulkResult()


class FakeDatabase:
    def __init__(self):
        self.collection = FakeCollection()

    def __getitem__(self, name):
        self.requested_name = name
        return self.collection


class FakeNormalizer:
    @staticmethod
    def _language(value):
        return "hi" if value == "आलू" else "en"

    def localized_options(self, values, field, language):
        translations = {
            ("आलू", "en"): "Potato",
            ("आलू", "hi"): "आलू",
        }
        return [{
            "value": value,
            "label": translations.get((value, language), value),
            "label_language": language,
            "method": "test_translation",
            "translation_evidence": {
                "model_family": "TestTranslationModel",
                "model_name": "test/local-translator",
                "source_language": self._language(value),
                "target_language": language,
                "validation_status": "test_validated",
                "official_value_preserved": True,
            },
        } for value in values]


class MandiCatalogLabelMongoTests(unittest.TestCase):
    def setUp(self):
        self.database = FakeDatabase()
        self.cache = MandiCatalogLabelMongo(
            self.database, normalizer=FakeNormalizer()
        )

    def test_sync_persists_both_languages_only_once(self):
        first = self.cache.sync("crop", ["आलू"])
        second = self.cache.sync("crop", ["आलू"])
        self.assertEqual(first, {"observed": 1, "created": 1})
        self.assertEqual(second, {"observed": 1, "created": 0})
        document = self.database.collection.documents[("crop", "आलू")]
        self.assertEqual(document["labels"], {"en": "Potato", "hi": "आलू"})
        self.assertEqual(document["label_policy_version"], 6)
        self.assertEqual(
            document["translation_evidence"]["en"]["model_name"],
            "test/local-translator",
        )

    def test_all_options_keep_official_value_and_both_labels(self):
        options = self.cache.options("crop", ["आलू"], language="all")
        self.assertEqual(options[0]["value"], "आलू")
        self.assertEqual(options[0]["labels"]["en"], "Potato")
        self.assertEqual(options[0]["labels"]["hi"], "आलू")
        self.assertTrue(
            options[0]["translation_evidence"]["en"][
                "official_value_preserved"
            ]
        )

    def test_single_language_option_exposes_selected_evidence(self):
        option = self.cache.options(
            "crop", ["आलू"], language="en"
        )[0]

        self.assertEqual(option["label"], "Potato")
        self.assertEqual(
            option["selected_translation_evidence"]["model_name"],
            "test/local-translator",
        )

    def test_policy_refresh_preserves_previous_translation_evidence(self):
        self.cache.sync("crop", ["आलू"])
        key = ("crop", "आलू")
        previous = self.database.collection.documents[key]
        previous["label_policy_version"] = 5
        previous["labels"] = {"en": "Bad label", "hi": "आलू"}
        previous["methods"] = {
            "en": "official_label_translation_rejected",
            "hi": "official_catalog_label",
        }
        previous["translation_evidence"] = {
            "en": {"proposed_label": "Bad label"},
            "hi": {},
        }

        refreshed = self.cache.sync("crop", ["आलू"])

        self.assertEqual(refreshed, {"observed": 1, "created": 1})
        document = self.database.collection.documents[key]
        self.assertEqual(len(document["translation_history"]), 1)
        history = document["translation_history"][0]
        self.assertEqual(history["label_policy_version"], 5)
        self.assertEqual(history["labels"]["en"], "Bad label")


if __name__ == "__main__":
    unittest.main()
