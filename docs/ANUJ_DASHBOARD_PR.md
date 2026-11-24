# Dashboard and evidence change scope

This branch extends the dashboard and evidence tools on top of main at
`ba9f537`. It does not replace the teammate implementations already in main.

## Included

- Local dashboard: Direct QA, a read-only ReAct option backed by Rishi’s
  existing LangChain factory, bilingual exact Arwal mandi price lookup,
  district trends, a period-report preview, and the interactive market map.
- Hosted static dashboard: revised evaluated snapshot, distance-aware market
  display, map zoom, and the optional satellite basemap.
- Local viva PDF upload: preview, explicit save and read-back in the separate
  `viva_document_uploads` collection, reopen and verify the identical PDF,
  reviewed exact table-cell values and highlights, and English/Hindi table
  answers. See [the walkthrough](VIVA_DASHBOARD.md).
- Separate provenance-first ingestion v2, reviewed PDF table profiles,
  bilingual normalization and historical JSONL evaluation evidence.
  See [ingestion details](AGENTIC_INGESTION_V2.md) and
  [the pinned read-only rehearsal](../eval/round2_demo_README.md).

## Outside this PR

- No change to the standalone chatbot, its graph, MongoDB/Milvus connectors,
  legacy ingestion/sync runtime, shared configuration, or credentials.
- No change to Rishi's CLI, shared agent configuration, resolver, ingest tools
  or wrappers. The dashboard hands his existing agent exactly one read-only
  tool. An explicit PDF save is a separate local dashboard action.
- No new Document Chat mode or multi-tool ReAct loop. Existing legacy
  entrypoints are not required to start or test this dashboard.

## Verify locally

From the repo root, with the existing Windows virtual environment:

```cmd
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe eval\round2_demo.py
set "API_HOST=127.0.0.1" && set "API_PORT=5004" && .venv\Scripts\python.exe data_api.py
```

Use the existing local MongoDB and Ollama services. Open
`http://127.0.0.1:5004/`; no database reseeding or vector synchronization is
needed for the already-tested Windows environment. For a new, empty local
MongoDB, `db/load_dump.py --mongo` is an explicit seed step, not part of app
startup. On the current local data, check Direct QA and ReAct with the English
and Hindi Arwal potato question and confirm the applied market, crop, price,
date and source. Reopen the saved verified PDF Run ID; reattach the original
PDF if the server has restarted, then check the Hindi-to-English Wheat →
Production exact source-cell highlight.
