"""Independent AgentEvals trajectories and code-based Phase 2 checks."""

import json
import re


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
    "grounded_qa": {
        "agent_id": "grounded_qa_agent",
        "tool_name": "ollama_grounded_qa",
        "required_inputs": {"question", "dry_run"},
    },
}


def _tool_call(tool_name, arguments):
    return {
        "function": {
            "name": tool_name,
            "arguments": json.dumps(
                arguments, ensure_ascii=False, sort_keys=True
            ),
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
                result.get("summary", {}), ensure_ascii=False, default=str,
                sort_keys=True,
            ),
        },
        {
            "role": "assistant",
            "content": f"Agent status: {result['status']}",
        },
    ]


def reference_trajectory(result, expected_tool_input=None):
    """Build a reference that can be independent of the observed result."""
    expected = EXPECTED_TOOLS[result["source_id"]]
    arguments = (
        expected_tool_input
        if expected_tool_input is not None
        else result.get("tool_input", {})
    )
    return [
        {"role": "user", "content": f"Process {result['source_id']}"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_tool_call(expected["tool_name"], arguments)],
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


def _numeric_tokens(value):
    return set(re.findall(r"(?<!\w)\d[\d,]*(?:\.\d+)?", str(value)))


def _qa_checks(summary, acceptance):
    answer = str(summary.get("answer", "")).strip()
    record_text = json.dumps(
        summary.get("records", []), ensure_ascii=False, default=str
    )
    checks = {
        "answer_present": bool(answer),
        "records_retrieved": summary.get("records_retrieved", 0)
        >= acceptance.get("min_records", 1),
        "sources_returned": summary.get("source_count", 0)
        >= acceptance.get("min_sources", 1),
        "numeric_fidelity": _numeric_tokens(answer).issubset(
            _numeric_tokens(record_text)
        ),
    }
    if acceptance.get("intent"):
        checks["intent_accuracy"] = (
            summary.get("intent") == acceptance["intent"]
        )
    if acceptance.get("answer_language"):
        checks["answer_language"] = (
            summary.get("answer_language") == acceptance["answer_language"]
        )
    return checks


def _case_checks(result, case_reference, trace):
    if not case_reference:
        return {}
    acceptance = case_reference.get("acceptance", {})
    summary = result.get("summary", {})
    checks = {
        "independent_tool_input": result.get("tool_input")
        == case_reference.get("expected_tool_input"),
    }
    if "min_records" in acceptance and result["source_id"] != "grounded_qa":
        processed = summary.get(
            "records_processed", summary.get("chunks_processed", 0)
        )
        checks["minimum_records"] = processed >= acceptance["min_records"]
    if "expected_records" in acceptance:
        checks["expected_records"] = (
            summary.get("records_processed") == acceptance["expected_records"]
        )
    if "expected_crop_groups" in acceptance:
        checks["expected_crop_groups"] = (
            summary.get("crop_groups") == acceptance["expected_crop_groups"]
        )
    if acceptance.get("period"):
        checks["expected_period"] = summary.get("period") == acceptance["period"]
    if "min_direct_pages" in acceptance:
        checks["direct_text_extraction"] = (
            summary.get("direct_pages", 0) >= acceptance["min_direct_pages"]
        )
    if "min_ocr_pages" in acceptance:
        checks["ocr_extraction"] = (
            summary.get("ocr_pages", 0) >= acceptance["min_ocr_pages"]
        )
    if acceptance.get("source_ids") is not None:
        observed = [item.get("source_id") for item in summary.get("sources", [])]
        checks["source_group"] = observed == acceptance["source_ids"]
    if "expected_retries" in acceptance:
        checks["retry_observed"] = (
            trace.get("automation_metrics", {}).get("retries")
            == acceptance["expected_retries"]
        )
    if result["source_id"] == "grounded_qa":
        checks.update(_qa_checks(summary, acceptance))
    return checks


def evaluate_trace(trace, case_reference=None):
    """Evaluate one trace, optionally against an independent case manifest."""
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
        expected_input = (
            case_reference.get("expected_tool_input")
            if case_reference else None
        )
        trajectory = evaluator(
            outputs=result_trajectory(result),
            reference_outputs=reference_trajectory(result, expected_input),
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
        checks.update(_case_checks(result, case_reference, trace))
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
        "case_id": case_reference.get("id") if case_reference else None,
        "run_id": trace.get("run_id"),
        "framework": "AgentEvals strict trajectory + independent checks",
        "passed": passed,
        "agents_evaluated": len(per_agent),
        "agents_passed": sum(item["passed"] for item in per_agent),
        "per_agent": per_agent,
        "automation": automation,
        "foundry_metric_mapping": {
            "task_completion": "code evaluator",
            "tool_selection": "independent agent/tool reference",
            "tool_input_accuracy": "independent exact case input",
            "tool_call_accuracy": "AgentEvals strict trajectory match",
            "tool_call_success": "observed tool result status",
            "tool_output_utilization": "case-specific output assertions",
            "groundedness": "retrieval, source, and numeric-fidelity checks",
        },
    }
