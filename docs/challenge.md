# Challenge, Evidence and Tool Selection

## Problem

Bihar agriculture information is published through sources that differ in access method, structure, language and update frequency. The project must collect daily mandi observations from a changing public service, normalize a long historical Excel workbook, recover evidence from English and scanned Hindi PDFs, preserve traceable source locations, and answer questions without allowing a language model to invent database operations or unsupported facts.

A single general-purpose extraction prompt was not suitable for all four responsibilities. Structured API data requires deterministic validation and pagination. The crop workbook requires layout-aware column alignment. Scanned Hindi documents require OCR. Natural-language questions require bounded model decisions followed by deterministic retrieval.

## Approaches tested on project sources

### Browser table extraction and the public mandi API

The first implementation used Playwright to read the visible Bihar Krishi table. It was useful for establishing the source and produced the ten rows displayed by the page, but it did not expose the historical volume required for temporal analysis.

Network-contract inspection identified the public `agriMarket` JSON endpoint. The direct client added explicit date bounds, pagination, official codes, stable source record IDs and retry handling. A 90-day run collected 7,345 observations from 21 July through 18 October 2026. A repeated two-day run matched all 58 existing observations and inserted none. The API client therefore replaced browser extraction as the operational mandi agent; the browser implementation remains historical evidence of the alternative tested.

### Direct PDF text and Tesseract OCR

`pypdf` was tested first because it is fast and preserves the existing text layer. Tesseract with PyMuPDF rendering was added only for pages without usable text. Across the four enabled documents, the measured run requested 75 pages and recovered 72: 40 through direct text and 32 through OCR, with three skipped pages. The result contained 153 searchable chunks. This selective design avoids OCR noise on native-text documents while supporting the two Hindi scanned publications.

### Keyword retrieval and multilingual hybrid retrieval

MongoDB keyword search was retained as a transparent lexical baseline. BGE-M3 semantic retrieval and reciprocal-rank fusion were then tested on six labelled questions. Keyword hit rate at five was 0.3333 and mean reciprocal rank was 0.3333. Hybrid retrieval reached 1.0000 on both measures and retrieved the expected source for all four cross-language cases. Qwen3 was retained for constrained query planning and grounded answer wording; it is not used to calculate prices, trends or database aggregates.

## Agent decomposition

| Agent | Source decision | Tool execution | Output |
|---|---|---|---|
| `daily_mandi_api_agent` | Date and pagination scope | Bihar Krishi API client | Daily normalized observations |
| `crop_statistics_excel_agent` | Workbook layout validation | pandas/openpyxl | Crop-season-year records |
| `multilingual_pdf_agent` | Direct text or OCR per page | pypdf/Tesseract | Page-aware evidence chunks |
| `grounded_qa_agent` | Intent, filters and answer language | MongoDB, BGE-M3 and Qwen3 | Grounded answer with citations |

The first three agents perform extraction. The QA agent is downstream: it can read only the allowlisted collections populated by those extractors.

## Research limitations and implementation limitations

Research limitations arise from the underlying methods. OCR can lose table geometry and confuse similar glyphs. Dense retrieval can return semantically related but irrelevant text. Small local language models can follow formatting and language instructions inconsistently.

Implementation limitations are narrower and can be improved in this repository. The optimized Excel parser currently targets the documented DA&FW layout. Seven market locations remain unresolved because the geocoder did not return sufficiently specific candidates. The local deployment uses a 4-billion-parameter Qwen model because the available workstation has 16 GB RAM. None of these limits is presented as a general limit of OCR, retrieval or language models.

## Design decisions

- Source-specific fixed code handles parsing, validation, unit rules and database identities.
- Model decisions are limited to the QA plan and answer wording inside validated schemas.
- Every stored record carries a run ID, extracting agent, source type and source locator.
- Ambiguous coordinates and unreadable pages remain unresolved rather than being guessed.
- Historical data is refreshed through idempotent upserts, allowing late source revisions without duplicate rows.

## Supporting literature

The design follows retrieval-augmented generation for evidence-bounded answers, dense multilingual retrieval for cross-language matching, and tool-trajectory evaluation for agent behaviour. The project-specific bibliography and rationale are maintained in `sources/literature.yaml` and `docs/CHALLENGE_AND_LITERATURE.md`. Principal references include Lewis et al. on retrieval-augmented generation, BGE-M3 for multilingual multi-function retrieval, the Tesseract OCR project, MongoDB text and geospatial indexing documentation, LangSmith tracing, and AgentEvals trajectory evaluation.

## Reproducible evidence

- `docs/evidence/phase2_final_suite.json`: seven manifest-driven cases, all passed.
- `docs/evidence/phase3_hybrid_retrieval.json`: keyword versus hybrid retrieval results.
- `docs/evidence/phase4_90day_backfill_live.json`: date-wise mandi collection trace.
- `docs/evidence/phase4_2day_duplicate_check.json`: duplicate-safe repeated collection.
- `docs/evidence/phase5_geospatial_final_summary.json`: 42 verified market locations out of 49 observed.
- `docs/evidence/phase6_visual_dashboard_smoke.json`: database and dashboard verification.
