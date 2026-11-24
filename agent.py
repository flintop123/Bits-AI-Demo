"""LangChain agent — the decision layer over existing, already-tested
agriculture data tools.

This agent does not scrape, parse, or write data itself. It reads a
free-text request and decides which already-validated capability in
agent_tools/ (each a thin @tool wrapper over an already-tested agent or
orchestrator) should handle it, then observes the result and composes a
final answer.

Built on LangChain 1.x's create_agent, which uses native tool calling: the
model returns a structured tool call, the framework runs it and feeds the
result back, and the loop ends when the model replies without a tool call.

run_extractor.py is the named CLI entry point for this agent
(`python run_extractor.py "<request>"`); it's a thin wrapper around
build_agent()/run() below.

This is additive to, not a replacement for, run_phase2_pipeline.py /
Phase2Supervisor. That orchestrator stays the deterministic, auditable path
used for scheduled ingestion and for the measured Phase 2 evaluation
(eval/run_eval.py, logs/automation_log.csv). This agent is for ad hoc,
human-directed requests where the source type isn't known in advance until
the model reads the request. See docs/REACT_AGENT.md for the comparison.

Usage:
    python agent.py "load last seven days of mandi data via api"
    python agent.py "what was total rice production in 2024-25?"
"""

import argparse
import sys

from langchain.agents import create_agent

from agent_config import get_chat_model
from agent_tools import (
    ask_agriculture_question,
    ingest_agriculture_documents,
    ingest_crop_statistics,
    ingest_mandi_prices,
)
from agent_tools._shared import ingestion_write_scope, wants_dry_run
from agent_tools.agent_logging import (
    AgentLogCallback,
    configure_logging,
)
from agent_tools.capabilities import (
    clarify,
    describe,
    request_after_choice,
    resolve_request,
)

SYSTEM_PROMPT = (
    "You handle requests about Bihar agriculture data. Choose the single "
    "best tool for the request and pass the request text to it. Ingestion "
    "tools fetch and store new data; the question tool only answers from "
    "data already stored. Before calling a tool, state in one short "
    "sentence why you chose it. When a tool returns its observation, "
    "answer the user's request from that observation."
)


def default_tools():
    return [
        ingest_mandi_prices,
        ingest_crop_statistics,
        ingest_agriculture_documents,
        ask_agriculture_question,
    ]


def build_agent(llm=None, tools=None):
    """Assemble the agent over the four existing capabilities.

    ``llm`` and ``tools`` are injectable so tests can substitute a scripted
    fake chat model and a trivial fake tool to verify the agent loop
    without calling Ollama or MongoDB. Production code should call this
    with no arguments.

    In production, the agent is only ever handed the four tools above —
    never arbitrary code execution — so the model's decision is bounded to
    picking one of a small, fixed, already-safe set of actions and filling
    in its arguments.
    """
    tools = tools if tools is not None else default_tools()
    llm = llm if llm is not None else get_chat_model()
    return create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)


def resolve_capability(
    request, *, logger, interactive, input_fn=input, output_fn=print
):
    """Fixed-code resolution step that runs before the model.

    Returns (capability, user_chose). capability is None if the request
    could not be resolved and the user did not pick one (cancelled, or
    non-interactive). user_chose is True when the user picked from options.
    """
    logger.info("Parsing human input and finding matching tool...")
    resolution = resolve_request(request)
    logger.info("Resolver: %s (%s)", resolution.status, resolution.reason)
    if resolution.status == "resolved":
        return resolution.capability, False

    if not interactive:
        output_fn(describe(resolution))
        logger.info("Non-interactive run: no tool selected, options listed")
        return None, False

    logger.info("Asking the user to choose a source")
    chosen = clarify(
        resolution, input_fn=input_fn, output_fn=output_fn
    )
    if chosen is None:
        logger.info("No source chosen; stopping without running a tool")
        return None, False
    logger.info("User selected: %s", chosen.label)
    return chosen, True


def run(
    request,
    verbose=True,
    *,
    llm=None,
    interactive=None,
    input_fn=input,
    output_fn=print,
    allow_write=False,
):
    """Resolve the request to one capability, then run the ReAct loop over
    just that capability's tool. Returns the final answer text, or a short
    message if nothing was run."""
    logger = configure_logging()
    logger.info('Human input = "%s"', request)
    if interactive is None:
        interactive = sys.stdin.isatty()

    capability, user_chose = resolve_capability(
        request, logger=logger, interactive=interactive,
        input_fn=input_fn, output_fn=output_fn,
    )
    if capability is None:
        return "No tool was selected for this request."

    agent_request = request
    if user_chose:
        agent_request = request_after_choice(capability, request)
        logger.info('Request passed to agent = "%s"', agent_request)

    tools_by_name = {t.name: t for t in default_tools()}
    logger.info(
        "Found required tool: %s | action: %s",
        capability.tool_name, capability.action,
    )
    agent = build_agent(llm=llm, tools=[tools_by_name[capability.tool_name]])

    final_state = None
    with ingestion_write_scope(
        allow_write=allow_write and not wants_dry_run(request),
    ):
        for state in agent.stream(
            {"messages": [{"role": "user", "content": agent_request}]},
            config={"callbacks": [AgentLogCallback(logger)]},
            stream_mode="values",
        ):
            final_state = state
            if verbose:
                state["messages"][-1].pretty_print()
    answer = final_state["messages"][-1].content
    logger.info("Final answer: %s", " ".join(str(answer).split())[:300])
    return answer


def parse_cli(argv, *, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description="Run the Bihar ReAct agent.")
    parser.add_argument("--non-interactive", action="store_true", help="Do not prompt for clarification.")
    parser.add_argument("--write", action="store_true", help="Allow ingestion writes; default is dry run.")
    parser.add_argument("request", nargs="+", help="Plain-language request.")
    options = parser.parse_args(argv)
    return " ".join(options.request), False if options.non_interactive else None, options.write


def main(argv=None):
    request, interactive, allow_write = parse_cli(argv)
    run(request, interactive=interactive, allow_write=allow_write)


if __name__ == "__main__":
    main()
