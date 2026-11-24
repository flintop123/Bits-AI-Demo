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
system doesn't know in advance which capability applies. Fixed code first
resolves the request to one capability (see "Resolution step" below), then
a LangChain 1.x agent (`create_agent`, Ollama `qwen3:4b`) runs over just
that capability's tool and decides what argument to pass it. The
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

### Resolution step (before the model)

`agent.run()` does not hand the raw request to the model. It first calls
`agent_tools/capabilities.py`, which holds the **capability table** — the
in-code list of what the agent can really do, one entry per
(domain, source format) pair mapped to a tool:

| Domain | Format | Tool |
|---|---|---|
| mandi | api | `ingest_mandi_prices` |
| crop_statistics | excel | `ingest_crop_statistics` |
| documents | pdf | `ingest_agriculture_documents` |
| question | stored data | `ask_agriculture_question` |

`resolve_request()` (fixed keyword code, no model) returns one of:

- **resolved** — exactly one capability matches; the agent is built with
  only that tool.
- **unsupported** — a real domain with a format it doesn't have, e.g.
  "load mandi data via excel" (mandi is API-only).
- **ambiguous** / **unclear** — several, or no, sources match.

For anything but *resolved*, the user is shown the valid options and asked
to pick a number; the chosen capability is then run. With
`--non-interactive` (or when stdin is not a terminal) the options are
printed and nothing runs. This replaces the model improvising a refusal.

After the user picks an option, the model is not given their original
wording: "load mandi data via excel" next to a crop-only tool makes a small
model refuse. `request_after_choice()` restates the request from the chosen
capability instead, keeping only the day count and dry-run flag that fixed
code can read from the original. The log shows it as
`Request passed to agent = "..."`.

To add a capability, add one entry to `CAPABILITIES` (and its tool to
`agent_tools/__init__.py` / `agent.default_tools()`);
`tests/test_agent_resolution.py` checks every entry maps to a real tool.

**PDF selection (second level).** Inside `ingest_agriculture_documents`,
`agent_tools/agriculture_documents_ingestion/selection.py` narrows the
manifest from the request: an exact source id, else the optional
`keywords` list on each entry in `sources/agriculture_sources.yaml`, else a
"hindi" / "english" filter ("mixed" documents satisfy either). With no
hint, all enabled PDFs are ingested as before. No match returns an
`ERROR:` observation listing the available sources.

### Run log

Each run writes short, informational lines to the console and to
`logs/agent_run.log` (git-ignored; separate from the Phase 2
`logs/automation_log.csv`):

```
Human input = "load mandi data via excel"
Parsing human input and finding matching tool...
Resolver: unsupported (mandi data is not available as excel)
Asking the user to choose a source
User selected: Crop area / production / yield from the Excel workbook
Found required tool: ingest_crop_statistics | action: reading crop statistics from the Excel workbook
Agent reason: <one sentence from the model, or "(not stated)"> | chose tool=... args=...
Performing action: reading crop statistics from the Excel workbook (tool=ingest_crop_statistics)
Tool result: status=completed; records_processed=...
Final answer: ...
```

The resolver lines are exact (fixed code). "Agent reason" is whatever
one-line rationale the model wrote before its tool call; the system prompt
asks for one, but a small local model may skip it.

### The four tools

Each tool in `agent_tools/` is a thin `@tool` wrapper around an
already-tested, already-used class or orchestrator — the model never
gains a capability that didn't already exist:

| Tool | Wraps | Writes to MongoDB? |
|---|---|---|
| `ingest_mandi_prices` | `phase4.mandi_orchestrator.DailyMandiOrchestrator` — official paginated API | only with explicit write permission |
| `ingest_crop_statistics` | `phase2.agents.CropStatisticsSourceAgent` | only with explicit write permission |
| `ingest_agriculture_documents` | `phase2.agents.AgricultureDocumentsSourceAgent` | only with explicit write permission |
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

The CLI resolver selects one of the four catalogued tools. The model is
given that tool only and supplies its text argument; it does not choose among
the four tools itself. The viva dashboard is read-only and reuses the same
builder with one grounded QA tool. The CLI defaults to preview and only `--write` can authorize
ingestion writes. If the original request says "dry run", it stays a dry
run even with `--write`, regardless of how the model phrases the tool
call. Library callers of `agent.run()` can explicitly pass
`allow_write=True`; direct tool calls outside that scope remain dry.

### Which decisions are the model's, and which are fixed code's

This is worth stating explicitly, since it's judged directly in the
demonstration protocol:

- **Fixed code (resolver):** which of the four tools applies to a given
  free-text request, including refusing unsupported combinations and asking
  the user to choose; which manifest PDFs a document request means.
- **Model-made:** what single text argument to pass the (already chosen)
  tool; when to stop and give a final answer. Inside `ask_agriculture_question` specifically, the model
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
python -m unittest tests.test_react_agent tests.test_agent_resolution
```

This is a mechanical sanity check, not a substitute for a real run — a live
run still needs `ollama pull qwen3:4b` and MongoDB available, same as the
rest of the project (see `README.md`).
