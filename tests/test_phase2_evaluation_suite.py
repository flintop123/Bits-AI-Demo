import tempfile
import unittest
from pathlib import Path

from phase2.evaluation_suite import (
    TransientFailureAgent,
    load_evaluation_cases,
    run_evaluation_suite,
)
from phase2.models import AgentResult, utc_now


class FixtureAgent:
    agent_id = "crop_statistics_excel_agent"
    source_id = "crop_statistics"
    tool_name = "pandas_excel_extractor"

    def __init__(self, inputs):
        self.inputs = inputs

    def execute(self, run_id, *, dry_run=False):
        return AgentResult(
            agent_id=self.agent_id,
            source_id=self.source_id,
            tool_name=self.tool_name,
            tool_input=self.inputs,
            status="completed",
            summary={
                "records_processed": 4372,
                "provenance": {
                    "extraction_run_id": run_id,
                    "extracting_agent": self.agent_id,
                    "source_type": "excel",
                    "extracted_at": utc_now(),
                },
            },
            completed_at=utc_now(),
        )


class Phase2EvaluationSuiteTests(unittest.TestCase):
    def test_manifest_resolves_project_paths_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "cases.yaml"
            manifest.write_text(
                "cases:\n"
                "  - id: crop\n"
                "    source_id: crop_statistics\n"
                "    expected_tool_input:\n"
                "      file: data/input.xlsx\n"
                "      dry_run: true\n"
                "    acceptance: {}\n",
                encoding="utf-8",
            )

            cases = load_evaluation_cases(manifest, project_root=root)

            self.assertEqual(
                cases[0]["expected_tool_input"]["file"],
                str((root / "data" / "input.xlsx").resolve()),
            )

    def test_transient_wrapper_uses_real_delegate_after_one_failure(self):
        inputs = {"file": "fixture.xlsx", "dry_run": True}
        wrapper = TransientFailureAgent(FixtureAgent(inputs))
        with self.assertRaisesRegex(RuntimeError, "injected transient"):
            wrapper.execute("run-1", dry_run=True)

        result = wrapper.execute("run-1", dry_run=True)

        self.assertEqual(result.summary["records_processed"], 4372)
        self.assertEqual(wrapper.calls, 2)

    def test_suite_aggregates_case_results(self):
        case = {
            "id": "crop",
            "source_id": "crop_statistics",
            "expected_tool_input": {
                "file": "fixture.xlsx", "dry_run": True
            },
            "acceptance": {"expected_records": 4372},
        }

        def evaluator(trace, case_reference):
            return {
                "passed": True,
                "case_id": case_reference["id"],
                "per_agent": [],
            }

        report = run_evaluation_suite(
            [case],
            agent_factory=lambda item: FixtureAgent(
                item["expected_tool_input"]
            ),
            trace_evaluator=evaluator,
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["cases_passed"], 1)
        self.assertEqual(report["automation_rate"], 1)


if __name__ == "__main__":
    unittest.main()
