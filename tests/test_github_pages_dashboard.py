import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GitHubPagesDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "docs" / "assets" / "dashboard.css").read_text(encoding="utf-8")
        cls.javascript = (ROOT / "docs" / "assets" / "dashboard.js").read_text(encoding="utf-8")
        cls.snapshot = json.loads(
            (ROOT / "docs" / "data" / "dashboard_snapshot.json").read_text(encoding="utf-8")
        )

    def test_page_is_static_and_links_required_assets(self):
        self.assertNotIn("{{", self.index)
        self.assertNotIn("{%", self.index)
        self.assertIn("./assets/dashboard.css", self.index)
        self.assertIn("./assets/dashboard.js", self.index)
        self.assertIn("./data/dashboard_snapshot.json", self.javascript)

    def test_snapshot_preserves_validated_coverage(self):
        self.assertEqual(len(self.snapshot["daily_records"]), 90)
        self.assertEqual(len(self.snapshot["locations"]), 42)
        self.assertEqual(self.snapshot["totals"]["mandi_records"], 7345)
        self.assertEqual(self.snapshot["evaluation"]["protocol_cases"], {"passed": 40, "total": 40})

    def test_bilingual_and_repository_content_is_present(self):
        self.assertIn("data-hi=", self.index)
        self.assertIn("https://github.com/flintop123/Bits-AI-Demo", self.index)
        self.assertIn("2026PHXP0108P", json.dumps(self.snapshot))

    def test_hybrid_qa_has_live_endpoint_and_honest_snapshot_fallback(self):
        self.assertIn('id="ask-form"', self.index)
        self.assertIn('id="question-input"', self.index)
        self.assertIn("http://127.0.0.1:5000", self.javascript)
        self.assertIn("Hosted evidence snapshot", self.javascript)
        self.assertIn("verified_examples", self.javascript)

    def test_no_known_utf8_mojibake_patterns(self):
        combined = self.index + self.css + self.javascript + json.dumps(self.snapshot, ensure_ascii=False)
        self.assertNotIn("à¤", combined)
        self.assertNotIn("â€”", combined)
        self.assertNotIn("Ã", combined)


if __name__ == "__main__":
    unittest.main()
