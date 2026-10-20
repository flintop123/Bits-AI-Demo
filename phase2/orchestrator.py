"""Deterministic supervisor for Bihar agriculture source agents."""

import uuid

from phase2.langsmith_tracing import langsmith_status, trace_context
from phase2.models import AgentResult, utc_now
from phase2.run_store import MemoryRunStore, event


class Phase2Supervisor:
    """Route known source types, retry failures, and preserve an audit trace."""

    def __init__(self, agents, run_store=None, max_retries=1):
        self.agents = {agent.source_id: agent for agent in agents}
        self.run_store = run_store or MemoryRunStore()
        self.max_retries = max_retries

    def run(self, source_ids, *, dry_run=False, continue_on_error=True):
        requested = list(dict.fromkeys(source_ids))
        unknown = sorted(set(requested) - self.agents.keys())
        if unknown:
            raise ValueError("Unknown source agent(s): " + ", ".join(unknown))
        if not requested:
            raise ValueError("At least one source agent must be selected")

        run_id = str(uuid.uuid4())
        started_at = utc_now()
        run = {
            "run_id": run_id,
            "orchestrator": "phase2_supervisor",
            "routing_strategy": "deterministic_source_type",
            "requested_sources": requested,
            "dry_run": dry_run,
            "status": "running",
            "started_at": started_at,
            "events": [],
            "langsmith": langsmith_status(),
        }
        self.run_store.start(run)
        results = []
        retries = 0
        tool_calls = 0

        with trace_context(
            "phase2-supervisor-run",
            inputs={"source_ids": requested, "dry_run": dry_run},
            metadata={"run_id": run_id},
        ) as supervisor_trace:
            for source_id in requested:
                agent = self.agents[source_id]
                self.run_store.add_event(run_id, event(
                    "agent_selected",
                    source_id=source_id,
                    agent_id=agent.agent_id,
                    reason="fixed mapping from source type to specialist agent",
                ))
                result = None
                for attempt in range(1, self.max_retries + 2):
                    tool_calls += 1
                    self.run_store.add_event(run_id, event(
                        "tool_invoked",
                        source_id=source_id,
                        agent_id=agent.agent_id,
                        tool_name=agent.tool_name,
                        attempt=attempt,
                    ))
                    try:
                        with trace_context(
                            f"{agent.agent_id}-execute",
                            run_type="tool",
                            inputs={
                                "run_id": run_id,
                                "source_id": source_id,
                                "dry_run": dry_run,
                                "attempt": attempt,
                            },
                            metadata={
                                "agent_id": agent.agent_id,
                                "tool_name": agent.tool_name,
                            },
                        ) as agent_trace:
                            result = agent.execute(run_id, dry_run=dry_run)
                            if agent_trace is not None:
                                agent_trace.end(outputs=result.to_dict())
                        self.run_store.add_event(run_id, event(
                            "tool_result",
                            source_id=source_id,
                            agent_id=agent.agent_id,
                            tool_name=result.tool_name,
                            attempt=attempt,
                            status="success",
                            summary=result.summary,
                        ))
                        break
                    except Exception as exc:
                        retrying = attempt <= self.max_retries
                        self.run_store.add_event(run_id, event(
                            "tool_result",
                            source_id=source_id,
                            agent_id=agent.agent_id,
                            tool_name=agent.tool_name,
                            attempt=attempt,
                            status="failed",
                            retrying=retrying,
                            error=f"{type(exc).__name__}: {exc}",
                        ))
                        if retrying:
                            retries += 1
                            continue
                        result = AgentResult(
                            agent_id=agent.agent_id,
                            source_id=source_id,
                            tool_name=agent.tool_name,
                            tool_input={"dry_run": dry_run},
                            status="failed",
                            error=f"{type(exc).__name__}: {exc}",
                            completed_at=utc_now(),
                        )
                results.append(result.to_dict())
                if result.status == "failed" and not continue_on_error:
                    break

            completed = sum(
                result["status"] == "completed" for result in results
            )
            failed = sum(result["status"] == "failed" for result in results)
            attempted = len(results)
            if failed == 0 and attempted == len(requested):
                status = "completed"
            elif completed:
                status = "partial_failure"
            else:
                status = "failed"
            metrics = {
                "inputs_attempted": attempted,
                "inputs_without_manual_intervention": completed,
                "automation_rate": (
                    round(completed / attempted, 4) if attempted else 0
                ),
                "manual_interventions": 0,
                "tool_calls": tool_calls,
                "retries": retries,
                "unnecessary_tool_calls": 0,
            }
            updates = {
                "status": status,
                "completed_at": utc_now(),
                "results": results,
                "automation_metrics": metrics,
            }
            self.run_store.finish(run_id, updates)
            completed_run = self.run_store.get(run_id)
            if supervisor_trace is not None:
                supervisor_trace.end(outputs={
                    "run_id": run_id,
                    "status": status,
                    "routing_strategy": run["routing_strategy"],
                    "results": results,
                    "automation_metrics": metrics,
                })

        return completed_run
