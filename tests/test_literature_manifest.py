import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources" / "literature.yaml"
LITERATURE = ROOT / "docs" / "CHALLENGE_AND_LITERATURE.md"


class LiteratureManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
        cls.references = cls.data["references"]
        cls.document = LITERATURE.read_text(encoding="utf-8")

    def test_reference_ids_and_urls_are_unique(self):
        ids = [reference["id"] for reference in self.references]
        urls = [reference["url"] for reference in self.references]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(all(url.startswith("https://") for url in urls))

    def test_each_reference_has_project_rationale(self):
        for reference in self.references:
            with self.subTest(reference=reference["id"]):
                self.assertTrue(reference["title"].strip())
                self.assertTrue(reference["authors"].strip())
                self.assertTrue(reference["kind"].strip())
                self.assertGreaterEqual(len(reference["project_use"].strip()), 30)

    def test_document_contains_every_manifest_url(self):
        for reference in self.references:
            with self.subTest(reference=reference["id"]):
                self.assertIn(reference["url"], self.document)

    def test_document_records_observed_phase2_results(self):
        required_evidence = (
            "4,372 records",
            "72 of 75 pages",
            "40 direct-text pages",
            "32 OCR pages",
            "153 chunks",
            "3 of 3 agents passed",
            "100%",
        )
        for value in required_evidence:
            with self.subTest(value=value):
                self.assertIn(value, self.document)


if __name__ == "__main__":
    unittest.main()
