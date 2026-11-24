# Main integration review

This candidate joins `main` at `ba9f537` (first parent) and
`anuj/product-integration-v1` at `df64057` (second parent). Both histories
are retained. Rishi's PR #24 is already in main; its equivalent changes had
also been replayed on the integration branch. Jeetendra's original ingestion
and chatbot commits are in main and remain visible in history.

## Conflict decisions

- **Rishi's ReAct:** retain his resolver, tool catalog, clarification, PDF
  selection, logging and LangChain builder. Keep the tested integration
  safeguards: CLI ingestion requires explicit write permission and the
  dashboard supplies only a read-only QA tool. No second ReAct loop.
- **Jeetendra's ingestion and chatbot:** retain the hardened product versions
  of his API/PDF intake, Milvus sync and LangGraph graph. Do not restore
  legacy automatic ingestion on startup, all-collections indexing,
  credential-bearing defaults, or machine-specific notebook outputs.
  The optional chatbot still uses `main.py serve`; browser integration of
  that chatbot is not part of this conflict-resolution merge.
- **MongoDB identity:** the automatic merge picked up a commented-out mandi
  identity-index call from the older main implementation. Retain the enabled
  identity check on the product branch.
- **Dashboard and evidence:** retain the tested bilingual PDF highlights,
  local QA and existing evaluation harnesses.

After those decisions, the runtime code matches the tested product branch.
The only extra changes relative to that branch are documentation and credits.
The removed cloud token can still exist in old Git history; deleting it in
the merged tree does not revoke it.

## Verify before requesting a merge

On the candidate branch, run the suite in the existing Windows virtual
environment, then run the live dashboard with the existing MongoDB and
Ollama services. Check Direct QA, the read-only ReAct dashboard option,
and the saved-PDF bilingual table workflow in English and Hindi.
Use the existing port and saved evidence; no database reseeding is needed.

```cmd
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Use a review branch, not a direct push to main. If either remote parent has
moved, check the changes before promoting this candidate.
