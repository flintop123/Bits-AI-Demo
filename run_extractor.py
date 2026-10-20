"""Constrained ReAct supervisor — plain-English entry point.

    python3.11 run_extractor.py "load last seven days of mandi data via api"

This is a thin CLI wrapper around agent.py's build_agent()/run(): a
LangChain ReAct agent that reads a free-text request and decides which of
the four already-tested capabilities in agent_tools/ applies, then calls it
and reports the result.

"Constrained" means the model is never handed anything beyond those four
fixed tools — no arbitrary code execution, no open-ended tool creation. It
is additive to, and does not change, run_phase2_pipeline.py's deterministic
Phase2Supervisor, which remains the orchestrator used for scheduled
ingestion and for the measured Phase 2 evaluation. See docs/REACT_AGENT.md.
"""

import sys

from agent import run

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python run_extractor.py "<plain English request>"')
        raise SystemExit(1)
    print(run(" ".join(sys.argv[1:])))
