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

    @patch("phase2.evaluation._trajectory_evaluator")
    def test_independent_case_detects_wrong_tool_input(self, factory):
        factory.return_value = lambda **kwargs: {"score": True}
        trace = {
            "run_id": "run-2",
            "automation_metrics": {"automation_rate": 1},
            "results": [{
                "source_id": "crop_statistics",
                "agent_id": "crop_statistics_excel_agent",
                "tool_name": "pandas_excel_extractor",
                "tool_input": {"file": "wrong.xlsx", "dry_run": True},
                "status": "completed",
                "summary": {"records_processed": 4372, "provenance": {
                    "extraction_run_id": "run-2",
                    "extracting_agent": "crop_statistics_excel_agent",
                    "source_type": "excel",
                    "extracted_at": "2026-10-17T00:00:00+00:00",
                }},
            }],
        }
        case = {
            "id": "independent",
            "expected_tool_input": {
                "file": "expected.xlsx", "dry_run": True
            },
            "acceptance": {"expected_records": 4372},
        }

        report = evaluate_trace(trace, case_reference=case)

        self.assertFalse(report["passed"])
        self.assertFalse(report["per_agent"][0]["checks"][
            "independent_tool_input"
        ])

    @patch("phase2.evaluation._trajectory_evaluator")
    def test_grounded_qa_checks_sources_language_and_numbers(self, factory):
        factory.return_value = lambda **kwargs: {"score": True}
        question = "What was rice production in 2024-25?"
        trace = {
            "run_id": "qa-run",
            "automation_metrics": {"automation_rate": 1},
            "results": [{
                "source_id": "grounded_qa",
                "agent_id": "grounded_qa_agent",
                "tool_name": "ollama_grounded_qa",
                "tool_input": {"question": question, "dry_run": True},
                "status": "completed",
                "summary": {
                    "answer": "Rice production was 8440825.31 tonnes in 2024-25.",
                    "answer_language": "en",
                    "intent": "crop_statistics",
                    "records_retrieved": 1,
                    "records": [{
                        "crop": "Rice", "production": 8440825.31,
                        "year": "2024-25",
                    }],
                    "source_count": 1,
                    "sources": [{"source": "DA&FW"}],
                    "provenance": {
                        "extraction_run_id": "qa-run",
                        "extracting_agent": "grounded_qa_agent",
                        "source_type": "grounded_query",
                        "extracted_at": "2026-10-17T00:00:00+00:00",
                    },
                },
            }],
        }
        case = {
            "id": "qa",
            "expected_tool_input": {"question": question, "dry_run": True},
            "acceptance": {
                "intent": "crop_statistics", "answer_language": "en",
                "min_records": 1, "min_sources": 1,
            },
        }

        report = evaluate_trace(trace, case_reference=case)

        self.assertTrue(report["passed"])
        self.assertTrue(report["per_agent"][0]["checks"][
            "numeric_fidelity"
        ])


if __name__ == "__main__":
    unittest.main()
