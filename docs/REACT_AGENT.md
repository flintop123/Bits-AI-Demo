# Constrained ReAct supervisor

This project has two separate orchestration paths over the same
specialist capabilities. Both are real and both are demonstrable; they
exist for different situations.

## 1. Phase2Supervisor — deterministic, auditable, used for evaluation

`run_phase2_pipeline.py` routes a known `--source` flag to its matching
agent via a fixed lookup (`Phase2Supervisor`, [phase2/orchestrator.py](../phase2/orchestrator.py)).
This is the path that produces `eval/phase2_metrics.csv`,
`logs/automation_log.csv`, and the fault-injection demonstration. It is
intentionally not model-driven: the source type is already known before the
run starts (a scheduled job, an evaluation case), so there is nothing for a
model to decide, and a deterministic router is the simpler, cheaper, fully
reproducible choice for that situation. This orchestrator is unchanged by
everything below.

## 2. run_extractor.py — a constrained ReAct agent, for free-text requests

For the opposite situation: a human gives a free-text request and the
system doesn't know in advance which capability applies. A LangChain 1.x
agent (`create_agent`, Ollama `qwen3:4b`) reads the request and decides,
one step at a time, which tool to call and what arguments to pass it. The
model returns a structured tool call, the framework runs it and feeds the
result back, and the loop ends when the model replies without a tool call.
"Constrained" means the model is never handed anything beyond four fixed,
already-safe tools — no arbitrary code execution, no open-ended tool
creation.

```powershell
python run_extractor.py "load last seven days of mandi data via api"
python run_extractor.py "what was total rice production in 2024-25?"
```

`run_extractor.py` is the named entry point; it's a thin wrapper around
`agent.py`'s `build_agent()`/`run()`, which stays importable as a library
for anything else that wants to embed the same agent.

### The four tools

Each tool in `agent_tools/` is a thin `@tool` wrapper around an
already-tested, already-used class or orchestrator — the model never
gains a capability that didn't already exist:

| Tool | Wraps | Writes to MongoDB? |
|---|---|---|
| `ingest_mandi_prices` | `phase4.mandi_orchestrator.DailyMandiOrchestrator` — the official paginated API client, the same `daily_mandi_api_agent` that `docs/source_agent_map.csv` and `eval/phase2_metrics.csv` already treat as canonical | yes (unless the request says "dry run") |
| `ingest_crop_statistics` | `phase2.agents.CropStatisticsSourceAgent` | yes (unless "dry run") |
| `ingest_agriculture_documents` | `phase2.agents.AgricultureDocumentsSourceAgent` | yes (unless "dry run") |
| `ask_agriculture_question` | `phase2.agents.GroundedQAAgent` | no — read-only |

`ingest_mandi_prices` also understands a date range in the request —
"last seven days", "past 14 days", "today" — via `agent_tools/_shared.py`'s
`extract_days()`, a fixed-code regex/word-list parser (digits and the
spelled-out numbers one through twenty, plus thirty), not a model decision.
It resolves the same way `run_phase4_mandi_pipeline.py --days N` does (it
imports and reuses that module's `resolve_dates()`), then calls
`DailyMandiOrchestrator.run()` directly. `Phase2Supervisor`'s own
`--source mandi` path (`phase2/agents.py`'s `MandiSourceAgent`, a Playwright
scrape of the HTML page — `mandi_web_agent`, not `daily_mandi_api_agent`) is
unrelated and untouched; it has no concept of a date range, so it couldn't
support a request like "last seven days" regardless.

The ReAct agent is only ever handed these four, fixed, already-validated
tools — never arbitrary code execution. The model's decision is bounded to
*which one of four known-safe actions to call, with what single text
argument*. Whether a call actually writes to MongoDB is still decided by
fixed code (`agent_tools/_shared.py:wants_dry_run`, a keyword check), not by
the model's judgement — the model picks the tool, fixed code still gates
the write.

### Which decisions are the model's, and which are fixed code's

This is worth stating explicitly, since it's judged directly in the
demonstration protocol:

- **Model-made:** which of the four tools applies to a given free-text
  request; what single text argument to pass it; when to stop and give a
  final answer. Inside `ask_agriculture_question` specifically, the model
  also makes a second, narrower decision — the query plan (intent +
  filters) used by `AgricultureQAService`.
- **Fixed code:** the actual extraction, validation, and MongoDB writes
  (unchanged from `phase2/agents.py` and `phase4/mandi_orchestrator.py`);
  whether a call is a dry run; how many days of mandi data to fetch
  (`extract_days()`'s regex/word-list parsing, not the model); error
  handling (every tool catches exceptions and returns an `"ERROR: ..."`
  observation instead of letting the agent crash); the bounded, non-growing
  set of tools the model is even allowed to see.

### Configuration

`agent_config.py` is the single place to configure the Ollama model and
MongoDB connection for this agent and its tools — see `.env.example`. It
reads the same environment variable names already used by
`services/ollama_client.py` and the `conn/*.py` MongoDB connectors, so one
`.env` file configures both this agent and the pre-existing pipeline.

### Verifying without a live model

`tests/test_react_agent.py` exercises the agent loop (model returns a tool
call, the tool runs, the model returns a final answer) against a scripted
fake chat model, checks that each
tool reports a failure as an `"ERROR: ..."` observation instead of raising,
and checks `extract_days()`'s day-range parsing directly — none of this
requires Ollama or MongoDB to be running. Run it with:

```powershell
python -m unittest tests.test_react_agent
```

This is a mechanical sanity check, not a substitute for a real run — a live
run still needs `ollama pull qwen3:4b` and MongoDB available, same as the
rest of the project (see `README.md`).
