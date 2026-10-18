import tempfile
import unittest
from pathlib import Path

from phase3.retrieval_evaluation import (
    evaluate_retrieval,
    load_retrieval_cases,
)


class FakeQueryService:
    def search_agriculture_documents(
        self, search_terms, limit, semantic_query=None
    ):
        if semantic_query is None:
            return [{"source_id": "keyword-source"}]
        return [{
            "source_id": "expected-source",
            "retrieval": {
                "mode": "semantic",
                "methods": ["semantic"],
            },
        }]


class Phase3RetrievalEvaluationTests(unittest.TestCase):
    def test_cross_language_semantic_hit_is_measured(self):
        cases = [{
            "id": "cross-language",
            "query": "English query for Hindi evidence",
            "keyword_query": "English query",
            "expected_source_ids": ["expected-source"],
            "cross_language": True,
        }]

        report = evaluate_retrieval(
            FakeQueryService(),
            cases,
            acceptance={
                "min_hybrid_hit_rate_at_k": 1.0,
                "min_cross_language_hits_at_k": 1,
            },
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["hybrid_hit_rate_at_k"], 1.0)
        self.assertEqual(report["metrics"]["cross_language_hits_at_k"], 1)

    def test_manifest_requires_expected_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.yaml"
            path.write_text(
                "cases:\n  - id: missing\n    query: test\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "expected_source_ids"):
                load_retrieval_cases(path)


if __name__ == "__main__":
    unittest.main()
