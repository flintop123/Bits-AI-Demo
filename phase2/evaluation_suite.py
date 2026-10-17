"""Manifest-driven, reproducible evaluation across all Phase 2 agents."""

from copy import deepcopy
from pathlib import Path

import yaml

from phase2.agents import (
    AgricultureDocumentsSourceAgent,
    CropStatisticsSourceAgent,
    GroundedQAAgent,
    MandiSourceAgent,
)
from phase2.evaluation import evaluate_trace
from phase2.orchestrator import Phase2Supervisor
from phase2.run_store import MemoryRunStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_MANIFEST = PROJECT_ROOT / "sources" / "phase2_evaluation_cases.yaml"


class TransientFailureAgent:
    """Fail once, then delegate to the real specialist agent."""

    def __init__(self, agent):
        self.agent = agent
        self.agent_id = agent.agent_id
        self.source_id = agent.source_id
        self.tool_name = agent.tool_name
        self.calls = 0

    def execute(self, run_id, *, dry_run=False):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("injected transient source failure")
        return self.agent.execute(run_id, dry_run=dry_run)


def load_evaluation_cases(path=DEFAULT_CASE_MANIFEST, project_root=PROJECT_ROOT):
    path = Path(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation manifest must contain non-empty cases")
    resolved = []
    seen = set()
    for raw_case in cases:
        case = deepcopy(raw_case)
        case_id = str(case.get("id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError("Evaluation case ids must be non-empty and unique")
        seen.add(case_id)
        expected = case.get("expected_tool_input")
        if not isinstance(expected, dict):
            raise ValueError(f"Case {case_id} needs expected_tool_input")
        for field in ("file", "manifest"):
            if field in expected:
                value = Path(expected[field])
                if not value.is_absolute():
                    value = Path(project_root) / value
                expected[field] = str(value.resolve())
        resolved.append(case)
    return resolved


def build_case_agent(case):
    source_id = case["source_id"]
    inputs = case["expected_tool_input"]
    if source_id == "mandi":
        agent = MandiSourceAgent(inputs["urls"])
    elif source_id == "crop_statistics":
        agent = CropStatisticsSourceAgent(inputs["file"])
    elif source_id == "agriculture_documents":
        agent = AgricultureDocumentsSourceAgent(
            manifest_path=inputs["manifest"],
            source_ids=inputs["source_ids"],
        )
    elif source_id == "grounded_qa":
        agent = GroundedQAAgent(inputs["question"])
    else:
        raise ValueError(f"Unknown evaluation source: {source_id}")
    if case.get("fault_injection") == "transient_once":
        return TransientFailureAgent(agent)
    if case.get("fault_injection"):
        raise ValueError(f"Unknown fault injection: {case['fault_injection']}")
    return agent


def run_evaluation_suite(cases, agent_factory=build_case_agent,
                         trace_evaluator=evaluate_trace):
    results = []
    for case in cases:
        agent = agent_factory(case)
        trace = Phase2Supervisor(
            [agent], run_store=MemoryRunStore(), max_retries=1
        ).run(
            [case["source_id"]],
            dry_run=case["expected_tool_input"].get("dry_run", True),
            continue_on_error=False,
        )
        evaluation = trace_evaluator(trace, case_reference=case)
        results.append({
            "case_id": case["id"],
            "description": case.get("description"),
            "source_id": case["source_id"],
            "fault_injection": case.get("fault_injection"),
            "passed": evaluation["passed"],
            "trace": trace,
            "evaluation": evaluation,
        })
    passed = sum(item["passed"] for item in results)
    return {
        "framework": "AgentEvals manifest-driven Phase 2 suite",
        "passed": bool(results) and passed == len(results),
        "cases_evaluated": len(results),
        "cases_passed": passed,
        "automation_rate": round(
            sum(item["trace"]["automation_metrics"]["automation_rate"]
                for item in results) / len(results), 4
        ) if results else 0,
        "results": results,
    }
