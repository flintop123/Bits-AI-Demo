# Product integration and verification

This patch is based on `anuj/round2-feedback-completion` at `18f91e4`. It brings
forward Jitendra's API/PDF intake, Milvus indexing and LangGraph chatbot without
bringing in the committed cloud credential or machine-specific paths. Your
Round 2 CLI, baseline grounded QA, audit artifacts, and table validation
remain available. Rishi's original ReAct CLI is unchanged; it should not be
exposed as a product endpoint or used for write-authorized rehearsals.

## Dashboard and map

Run `python data_api.py` with your existing local MongoDB and open the printed
loopback address. Search by the official market name, district or numeric market
code. Choose a district, select a pin or directory entry, inspect the official
coordinates and available coordinate source, then use that market as the
centre or pick a point on the map. Set a 1–300 km radius. Distances are
straight-line estimates between locality centroids, not directions or travel
times. The live map can submit the existing nearby-price form; the map
distinguishes geographic coverage from markets present in capped price results.

For a no-database demo, serve `docs` using `python -m http.server 8000 --directory docs`.
The hosted map uses the committed snapshot, not the live database. Its radius
counts verified snapshot coordinates only. Basemap tiles are fetched on demand
from OpenStreetMap and retain attribution. The keyboard-accessible directory,
filters and distances still work if the tile service or Leaflet is unavailable.

## Optional intake and retrieval

Run commands from the project root using the existing virtual environment:

```text
python main.py preview-pdf --input path/to/report.pdf
python main.py preview-api --url https://example.test/public.json
python main.py sync --collection agri_public_v1
```

- API intake requires the exact HTTPS host under `document_ingestion.api_hosts`.
  It reads public JSON, simple HTML tables, HTML text or plain text without
  running scripts, sharing headers, or following redirects. Requests, bytes and
  row counts are bounded. The preview includes a response hash and row locators.
  A source that requires complex HTML layout or client-rendered tables needs
  a reviewed source-specific adapter. `--write` is deliberate and stores raw
  evidence, not approved agriculture observations.
- PDF intake keeps source text, language, and chunk identity. Opt-in
  `--translate` stores derived English separately as unverified machine output
  and may download the local model weights on first use. The verified
  `ingestion_v2.pdf_tables` workflow remains the route for reviewed numeric tables.
  Previous OCR mistakes and records written under older code are not repaired.
- Milvus sync without `--write` prints a plan without connecting anywhere.
  Configure exact reviewed public source URLs under
  `document_ingestion.approved_document_sources`. The write path only reads
  projected source fields from matching `agriculture_documents` records and
  creates a new corpus. It never overwrites an existing collection or
  automatically activates a new one. This avoids stale vectors from prior
  builds; create a new corpus for each change and leave prior versions inactive.
  Use a disposable local Milvus server for acceptance tests. A failed build
  can leave an unselected collection: do not activate it. A remote write target
  additionally needs `--allow-remote` and HTTPS.
- After verifying a loaded corpus, set `AGRI_MILVUS_COLLECTION` to its reviewed
  name and run `python main.py serve`. The optional chatbot starts at
  `127.0.0.1:5002` without debug mode. Prefer POSTing a JSON question to
  `/bihar-crop-chatbot/ask`. Set `AGRI_RAG_ACCESS_KEY` for bearer authentication
  on a shared workstation. It is stateless: it does not claim conversation
  memory. The original question and optional model-generated lookups supply
  evidence. Citation IDs resolve to returned excerpts and source locators.
  Missing or out-of-range citations return an abstention. This checks mapping,
  not whether a generated claim is logically entailed by the evidence.
- `AGRI_MILVUS_URI` and `AGRI_MILVUS_TOKEN` are environment-only settings.
  Never commit a real token. The known token on the old main history must be
  rotated by its owner; this patch cannot revoke it or rewrite Git history.

## Acceptance

In addition to the test suite, validate one public source on a disposable
local Milvus instance, confirm the query and ingest embedding model match,
review citations against original pages, and check Hindi and English
questions with correct, irrelevant and absent evidence. On the live dashboard
compare the Arwal 1 km and 75 km radii, inspect the list/map result counts,
test a district filter and a tile outage, and test on a narrow screen.
