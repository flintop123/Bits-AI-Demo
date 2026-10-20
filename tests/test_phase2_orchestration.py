import unittest
from contextlib import contextmanager
from unittest.mock import patch

from phase2.models import AgentResult, utc_now
from phase2.orchestrator import Phase2Supervisor
from phase2.run_store import MemoryRunStore


class FakeAgent:
    agent_id = "fake_agent"
    source_id = "fake_source"
    tool_name = "fake_tool"

    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0

    def execute(self, run_id, *, dry_run=False):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary source error")
        return AgentResult(
            agent_id=self.agent_id,
            source_id=self.source_id,
            tool_name=self.tool_name,
            tool_input={"dry_run": dry_run},
            status="completed",
            summary={
                "records_processed": 2,
                "provenance": {
                    "extraction_run_id": run_id,
                    "extracting_agent": self.agent_id,
                    "source_type": "fixture",
                    "extracted_at": utc_now(),
                },
            },
            completed_at=utc_now(),
        )


class Phase2OrchestrationTests(unittest.TestCase):
    def test_langsmith_spans_capture_agent_and_supervisor_outputs(self):
        spans = []

        class RecordingSpan:
            def __init__(self, name, options):
                self.name = name
                self.options = options
                self.outputs = None

            def end(self, *, outputs=None, **kwargs):
                self.outputs = outputs

        @contextmanager
        def recording_trace(name, **options):
            span = RecordingSpan(name, options)
            spans.append(span)
            yield span

        with patch(
            "phase2.orchestrator.trace_context",
            new=recording_trace,
        ):
            trace = Phase2Supervisor(
                [FakeAgent()], run_store=MemoryRunStore()
            ).run(["fake_source"], dry_run=True)

        supervisor_span, agent_span = spans
        self.assertEqual(supervisor_span.name, "phase2-supervisor-run")
        self.assertEqual(supervisor_span.outputs["status"], "completed")
        self.assertEqual(supervisor_span.outputs["automation_metrics"][
            "automation_rate"
        ], 1)
        self.assertEqual(agent_span.options["run_type"], "tool")
        self.assertEqual(agent_span.outputs["status"], "completed")
        self.assertEqual(agent_span.outputs["tool_name"], "fake_tool")

    def test_supervisor_records_selection_tool_result_and_metrics(self):
        store = MemoryRunStore()
        trace = Phase2Supervisor(
            [FakeAgent()], run_store=store, max_retries=1
        ).run(["fake_source"], dry_run=True)

        self.assertEqual(trace["status"], "completed")
        self.assertEqual(
            [item["event"] for item in trace["events"]],
            ["agent_selected", "tool_invoked", "tool_result"],
        )
        self.assertEqual(trace["automation_metrics"]["automation_rate"], 1)
        self.assertEqual(trace["automation_metrics"]["manual_interventions"], 0)

    def test_transient_failure_is_retried_and_exposed(self):
        agent = FakeAgent(failures=1)
        trace = Phase2Supervisor(
            [agent], run_store=MemoryRunStore(), max_retries=1
        ).run(["fake_source"])

        self.assertEqual(trace["status"], "completed")
        self.assertEqual(trace["automation_metrics"]["retries"], 1)
        self.assertEqual(trace["automation_metrics"]["tool_calls"], 2)
        failed_events = [
            item for item in trace["events"]
            if item["event"] == "tool_result" and item["status"] == "failed"
        ]
        self.assertTrue(failed_events[0]["retrying"])

    def test_permanent_failure_is_not_hidden(self):
        trace = Phase2Supervisor(
            [FakeAgent(failures=5)],
            run_store=MemoryRunStore(),
            max_retries=1,
        ).run(["fake_source"])

        self.assertEqual(trace["status"], "failed")
        self.assertEqual(trace["results"][0]["status"], "failed")
        self.assertIn("temporary source error", trace["results"][0]["error"])
        self.assertEqual(trace["automation_metrics"]["automation_rate"], 0)

    def test_unknown_source_is_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "Unknown source"):
            Phase2Supervisor([FakeAgent()]).run(["missing"])


if __name__ == "__main__":
    unittest.main()
