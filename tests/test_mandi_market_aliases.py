import tempfile
import unittest
from pathlib import Path

import yaml

from enrich_mandi_locations import load_aliases


class MandiMarketAliasManifestTests(unittest.TestCase):
    def test_project_manifest_has_unique_evidence_backed_aliases(self):
        aliases = load_aliases("sources/mandi_market_aliases.yaml")
        self.assertGreaterEqual(len(aliases), 20)
        for code, item in aliases.items():
            self.assertTrue(item["query_names"], code)
            self.assertTrue(item["query_district"], code)
            self.assertTrue(item["district_aliases"], code)
            self.assertTrue(item["evidence_url"].startswith("https://"), code)
            self.assertTrue(item["evidence_note"], code)

    def test_duplicate_market_code_is_rejected(self):
        payload = {
            "schema_version": 1,
            "aliases": [
                {
                    "market_code": 1,
                    "query_names": ["First"],
                    "evidence_url": "https://example.test/one",
                },
                {
                    "market_code": 1,
                    "query_names": ["Second"],
                    "evidence_url": "https://example.test/two",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aliases.yaml"
            path.write_text(
                yaml.safe_dump(payload),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_aliases(path)

    def test_alias_without_evidence_is_rejected(self):
        payload = {
            "schema_version": 1,
            "aliases": [{"market_code": 1, "query_names": ["Place"]}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aliases.yaml"
            path.write_text(
                yaml.safe_dump(payload),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "HTTPS evidence"):
                load_aliases(path)


if __name__ == "__main__":
    unittest.main()
