"""AgentEvals trajectory and code-based Phase 2 evaluators."""

import json


EXPECTED_TOOLS = {
    "mandi": {
        "agent_id": "mandi_web_agent",
        "tool_name": "playwright_mandi_extractor",
        "required_inputs": {"urls", "dry_run"},
    },
    "crop_statistics": {
        "agent_id": "crop_statistics_excel_agent",
        "tool_name": "pandas_excel_extractor",
        "required_inputs": {"file", "dry_run"},
    },
    "agriculture_documents": {
        "agent_id": "multilingual_pdf_agent",
        "tool_name": "pypdf_tesseract_extractor",
        "required_inputs": {"manifest", "source_ids", "dry_run"},
    },
}


def _tool_call(tool_name, arguments):
    return {
        "function": {
            "name": tool_name,
            "arguments": json.dumps(arguments, sort_keys=True),
        }
    }


def result_trajectory(result):
    return [
        {"role": "user", "content": f"Process {result['source_id']}"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                _tool_call(result["tool_name"], result.get("tool_input", {}))
            ],
        },
        {
            "role": "tool",
            "content": json.dumps(
                result.get("summary", {}), default=str, sort_keys=True
            ),
        },
        {
            "role": "assistant",
            "content": f"Agent status: {result['status']}",
        },
    ]


def reference_trajectory(result):
    expected = EXPECTED_TOOLS[result["source_id"]]
    return [
        {"role": "user", "content": f"Process {result['source_id']}"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                _tool_call(expected["tool_name"], result.get("tool_input", {}))
            ],
        },
        {"role": "tool", "content": "Expected source extraction result"},
        {"role": "assistant", "content": "Expected completion status"},
    ]


def _trajectory_evaluator():
    try:
        from agentevals.trajectory.match import (
            create_trajectory_match_evaluator,
        )
    except ImportError as exc:
        raise RuntimeError(
            "AgentEvals is not installed. Run: python -m pip install -r "
            "requirements.txt"
        ) from exc
    return create_trajectory_match_evaluator(
        trajectory_match_mode="strict",
        tool_args_match_mode="exact",
    )


def evaluate_trace(trace):
    evaluator = _trajectory_evaluator()
    per_agent = []
    for result in trace.get("results", []):
        source_id = result["source_id"]
        expected = EXPECTED_TOOLS.get(source_id)
        if expected is None:
            per_agent.append({
                "source_id": source_id,
                "error": "No evaluation reference is defined",
                "passed": False,
            })
            continue
        trajectory = evaluator(
            outputs=result_trajectory(result),
            reference_outputs=reference_trajectory(result),
        )
        tool_input = result.get("tool_input", {})
        checks = {
            "trajectory_match": bool(trajectory["score"]),
            "tool_selection": (
                result.get("agent_id") == expected["agent_id"]
                and result.get("tool_name") == expected["tool_name"]
            ),
            "tool_input_accuracy": expected["required_inputs"].issubset(
                tool_input
            ),
            "tool_call_success": result.get("status") == "completed",
            "task_completion": result.get("status") == "completed",
            "provenance_completeness": all(
                result.get("summary", {}).get("provenance", {}).get(field)
                for field in (
                    "extraction_run_id", "extracting_agent",
                    "source_type", "extracted_at",
                )
            ),
        }
        per_agent.append({
            "source_id": source_id,
            "agent_id": result.get("agent_id"),
            "checks": checks,
            "passed": all(checks.values()),
        })

    metrics = trace.get("automation_metrics", {})
    automation = {
        "rate": metrics.get("automation_rate", 0),
        "manual_interventions": metrics.get("manual_interventions", 0),
        "retries": metrics.get("retries", 0),
        "unnecessary_tool_calls": metrics.get("unnecessary_tool_calls", 0),
    }
    passed = bool(per_agent) and all(item["passed"] for item in per_agent)
    return {
        "run_id": trace.get("run_id"),
        "framework": "AgentEvals deterministic trajectory match",
        "passed": passed,
        "agents_evaluated": len(per_agent),
        "agents_passed": sum(item["passed"] for item in per_agent),
        "per_agent": per_agent,
        "automation": automation,
        "foundry_metric_mapping": {
            "task_completion": "implemented as code evaluator",
            "tool_selection": "implemented as reference mapping check",
            "tool_input_accuracy": "implemented as required-field check",
            "tool_call_accuracy": "implemented by AgentEvals strict trajectory match",
            "tool_call_success": "implemented from observed tool result status",
            "tool_output_utilization": "covered by trace result and downstream persistence",
            "groundedness": "evaluated separately for the QA agent",
        },
    }
