import unittest
from unittest.mock import patch

from phase2.evaluation import evaluate_trace


class Phase2EvaluationTests(unittest.TestCase):
    @patch("phase2.evaluation._trajectory_evaluator")
    def test_reference_checks_are_reported_per_agent(self, factory):
        factory.return_value = lambda **kwargs: {"score": True}
        trace = {
            "run_id": "run-1",
            "automation_metrics": {
                "automation_rate": 1,
                "manual_interventions": 0,
                "retries": 0,
                "unnecessary_tool_calls": 0,
            },
            "results": [{
                "source_id": "crop_statistics",
                "agent_id": "crop_statistics_excel_agent",
                "tool_name": "pandas_excel_extractor",
                "tool_input": {"file": "fixture.xlsx", "dry_run": True},
                "status": "completed",
                "summary": {"provenance": {
                    "extraction_run_id": "run-1",
                    "extracting_agent": "crop_statistics_excel_agent",
                    "source_type": "excel",
                    "extracted_at": "2026-10-17T00:00:00+00:00",
                }},
            }],
        }

        report = evaluate_trace(trace)

        self.assertTrue(report["passed"])
        self.assertEqual(report["agents_passed"], 1)
        self.assertTrue(all(report["per_agent"][0]["checks"].values()))


if __name__ == "__main__":
    unittest.main()
