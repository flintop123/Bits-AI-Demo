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

import sys

from langchain.agents import create_agent

from agent_config import get_chat_model
from agent_tools import (
    ask_agriculture_question,
    ingest_agriculture_documents,
    ingest_crop_statistics,
    ingest_mandi_prices,
)

SYSTEM_PROMPT = (
    "You handle requests about Bihar agriculture data. Choose the single "
    "best tool for the request and pass the request text to it. Ingestion "
    "tools fetch and store new data; the question tool only answers from "
    "data already stored. When a tool returns its observation, answer the "
    "user's request from that observation."
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


def run(request, verbose=True):
    agent = build_agent()
    final_state = None
    for state in agent.stream(
        {"messages": [{"role": "user", "content": request}]},
        stream_mode="values",
    ):
        final_state = state
        if verbose:
            state["messages"][-1].pretty_print()
    return final_state["messages"][-1].content


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python agent.py "<free text request>"')
        raise SystemExit(1)
    print(run(" ".join(sys.argv[1:])))
