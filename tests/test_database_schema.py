import json
import unittest
from pathlib import Path

from conn.agriculture_documents_mongodb import AgricultureDocumentsMongo
from conn.crop_statistics_mongodb import CropStatisticsMongo
from conn.mongodb import BiharCropMongo
from conn.mandi_locations import MandiLocationMongo
from conn.mandi_catalog_labels import MandiCatalogLabelMongo
from export_database_evidence import COLLECTION_PROJECTIONS, PROVENANCE_FIELDS


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "schema" / "bihar_agriculture.schema.json"


class DatabaseSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.collections = cls.schema["collections"]

    def test_all_runtime_collections_are_documented(self):
        self.assertEqual(
            set(self.collections),
            {
                "mandi_prices",
                "mandi_locations",
                "mandi_catalog_labels",
                "crop_statistics",
                "agriculture_documents",
                "agent_runs",
                "mandi_ingestion_runs",
            },
        )

    def test_documented_identity_fields_match_connectors(self):
        expected = {
            "mandi_prices": list(BiharCropMongo.IDENTITY_FIELDS),
            "mandi_locations": list(MandiLocationMongo.IDENTITY_FIELDS),
            "mandi_catalog_labels": list(
                MandiCatalogLabelMongo.IDENTITY_FIELDS
            ),
            "crop_statistics": list(CropStatisticsMongo.IDENTITY_FIELDS),
            "agriculture_documents": list(
                AgricultureDocumentsMongo.IDENTITY_FIELDS
            ),
        }
        for collection, identity_fields in expected.items():
            self.assertEqual(
                self.collections[collection]["identity_fields"],
                identity_fields,
            )

    def test_content_collections_require_shared_provenance(self):
        expected = set(PROVENANCE_FIELDS)
        self.assertEqual(
            set(self.schema["shared_provenance_fields"]), expected
        )
        for collection in COLLECTION_PROJECTIONS:
            required = set(self.collections[collection]["required"])
            self.assertTrue(expected.issubset(required), collection)

    def test_every_identity_has_a_matching_unique_index(self):
        for name, collection in self.collections.items():
            identity = collection["identity_fields"]
            unique_keys = [
                index["keys"]
                for index in collection["indexes"]
                if index.get("unique")
            ]
            self.assertTrue(
                any(keys[:len(identity)] == identity for keys in unique_keys),
                name,
            )


if __name__ == "__main__":
    unittest.main()
