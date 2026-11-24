# Agentic Ingestion V2 — Phase II Round-2 Evidence Report

**Project:** AgriAgent, CS F407 Artificial Intelligence, Group 17
**Evaluation date:** 15 November 2026
**Implementation branch:** `anuj/agentic-ingestion-v2-foundation`
**Scope:** Surprise-file inspection, extraction, schema mapping, validation, provenance, persistence and audit evidence. The existing ReAct layer was deliberately left unchanged.

## 1. Executive result

Five evaluator-style files spanning JSON, a wide Excel workbook, a scanned Hindi PDF and two native-text PDFs were processed through the V2 ingestion pipeline. After repairing the failure modes discovered during dry runs, **158 of 158 canonical records/chunks were validated and persisted** into the intended MongoDB collections.

| Input | Modality | Intended collection | Final result | Persistence behaviour |
|---|---|---|---:|---|
| `JSON_mandi_prices.json` | JSON, Hindi/English fields | `mandi_prices` | 15/15 | 15 new records |
| `Excel_crop_area_production_yield.xlsx` | Wide Excel time series | `crop_statistics` | 75/75 | 75 idempotent updates; no duplicates |
| `ScannedPDF_makhana.pdf` | Scanned Hindi PDF | `agriculture_documents` | 32/32 | Forced-OCR page/chunks |
| `PDF_annual_scheme_agriculture.pdf` | Native-text English PDF | `agriculture_documents` | 30/30 | 30 new chunks |
| `PDF_horticulture_brochure.pdf` | Multi-column English PDF | `agriculture_documents` | 6/6 | 6 new chunks |
| **Total** | **Four input patterns** | **Three collections** | **158/158** | **Validated writes only** |

The pipeline remained dry-run by default. MongoDB writes occurred only after an explicit `--write` flag and only after successful dry-run review. Formal Pydantic contracts, LangChain structured-tool schemas, target-collection allowlisting, confidence gates and connector-level unique identities constrained model-proposed mappings.

## 2. Database outcome

| Collection | Before V2 writes | After V2 writes | Net change | Explanation |
|---|---:|---:|---:|---|
| `mandi_prices` | 7,698 | 7,713 | +15 | New surprise JSON records |
| `crop_statistics` | 4,372 | 4,372 | 0 | 75 matching crop/season/year identities updated in place |
| `agriculture_documents` | 153 | 221 | +68 | 32 scanned-PDF + 30 annual-report + 6 brochure chunks |
| `mandi_locations` | 42 | 42 | 0 | No PDF was allowed to enter this structured collection |
| **Total validated portable dump** | **12,265** | **12,348** | **+83** | 15 new mandi records plus 68 new document chunks; crop records were updated in place |

The portable dump was exported after persistence and validated with:

```cmd
python db\load_dump.py --validate-only
```

Result: **12,348 valid records**.

## 3. Failure-to-fix evidence

The Round-2 work retained failures as engineering evidence instead of hiding them.

| Input/stage | Initial observed failure | Root cause | Safeguard introduced | Final outcome |
|---|---|---|---|---:|
| Mandi JSON mapping | 0/15 valid | Model omitted required `date` although it existed under the exact source name | Required-field restoration using exact-name schema safeguard, followed by canonical validation | 15/15 |
| Wide Excel mapping | 0/20 initial candidates | Model identified crop and season but omitted the header row and period-series mappings | Explicit wide-header repair; row 6 treated as header; five periods unpivoted for 15 crops | 75/75 |
| Scanned PDF routing | 0/32 valid; incorrectly proposed `mandi_locations` | Model-selected target was inconsistent with extracted document-chunk schema | Extractor/target compatibility guard redirected canonical PDF chunks to `agriculture_documents` | 32/32 |
| Scanned PDF quality | 32 traceable records but corrupted Hindi from embedded text | `pypdf` returned a low-quality hidden text layer | Forced Tesseract `hin+eng` OCR; stable page/chunk identity used for in-place replacement | 32/32 OCR |
| OCR rechunk reconciliation | 30 records updated; 2 obsolete `pypdf` chunks remained | OCR produced a slightly different chunk partition on pages 7 and 8 | Two stale records were inspected and deleted using the exact old run ID, filename and method | 0 stale chunks |
| Annual PDF | No blocking failure | Native text was readable; only minor spacing artefacts | Kept `pypdf` to avoid unnecessary OCR degradation | 30/30 |
| Horticulture brochure | Multi-column ordering artefacts | PDF drawing order differs from visual reading order | Stored as narrative evidence rather than promoting layout-derived values to structured facts | 6/6 |

## 4. Final write runs

| Evidence item | Run ID | Collection | Records associated with run |
|---|---|---|---:|
| Mandi JSON | `1adcd0d4-e8a3-4e52-90dc-db34badb1e31` | `mandi_prices` | 15 |
| Wide crop Excel | `fb210766-bd5b-4ab7-a228-5f6c7150fd25` | `crop_statistics` | 75 |
| Corrected scanned PDF | `4812ab68-154b-4406-bc93-5b63b74eed48` | `agriculture_documents` | 32 |
| Annual-scheme PDF | `273c1179-cba9-4197-bb81-f556e069232d` | `agriculture_documents` | 30 |
| Horticulture brochure | `544bc510-e019-4ea0-8b44-bade13617143` | `agriculture_documents` | 6 |

Each run writes an evidence bundle under `artifacts/ingestion_v2/<run-id>/` during execution. The bundle includes stage outputs and `events.jsonl`; the final portable MongoDB records retain the run ID and field provenance.

## 5. Provenance demonstrated

### 5.1 JSON field provenance

A stored mandi record from JSON array element 14 retained:

- source: `JSON_mandi_prices.json`;
- original file URI;
- JSONPath for every field, for example `$[14].district`, `$[14].date` and `$[14].price`;
- raw field and value;
- transformation (`identity` in this example);
- mapping method (`model_proposed_schema_mapping`);
- mapping confidence (0.99);
- source hash, source-record identity and extraction run ID.

Hindi values such as district, market and crop remained Unicode text in MongoDB.

### 5.2 Excel cell provenance

The record `Rice / Total / 2020-21` retained the following trace:

| Canonical field | Source location | Raw value | Method |
|---|---|---:|---|
| `crop` | `Bihar crops!A7` | Rice | Model-proposed direct mapping |
| `season` | `Bihar crops!B7` | Total | Model-proposed direct mapping |
| `year` | Period header for row 7 | 2020-21 | Wide-header safeguard |
| `area_hectares` | `Bihar crops!C7` | 3,020,860 | Wide-header safeguard |
| `production` | `Bihar crops!H7` | 6,746,989.1 | Wide-header safeguard |
| `yield_kg_per_hectare` | `Bihar crops!M7` | 2,233 | Wide-header safeguard |

This proves that a normalized value can be traced back to the workbook, worksheet, row, column and cell.

### 5.3 PDF page/chunk provenance

The corrected scanned-PDF records retained:

- source file and URI;
- page number;
- chunk index;
- declared/detected language;
- extraction method `tesseract_ocr`;
- raw content and field-level locator;
- extraction run ID.

The first corrected chunk was page 1, chunk 0 and began with readable Hindi text: “कार्यकारी सारांश / परिचय और पृष्ठभूमि / मखाना …”. This replaced the visibly corrupted hidden-text extraction without creating duplicate page/chunk identities.

## 6. Tool and safety architecture

The V2 pipeline exposes structured tools for inspection, extraction, schema mapping, validation and persistence. Every tool has an input and output JSON schema. Unknown tool arguments are rejected. LangChain adapters expose structured argument schemas, but model output is not directly executed as a database command.

Safety boundaries include:

1. dry-run is the default;
2. `--write` is an explicit operator decision;
3. target collections are enumerated and allowlisted;
4. canonical Pydantic models reject missing or invalid required fields;
5. low-confidence records are quarantined from writes;
6. connector-specific unique identities make retries idempotent;
7. deterministic safeguards may repair an unsafe or incomplete model proposal, with the safeguard method recorded in provenance;
8. the existing ReAct layer was not modified by this branch.

## 7. Backup and recoverability

Two compressed MongoDB archives were created outside the repository:

| Recovery point | File |
|---|---|
| Before V2 writes | `D:\BiharAgriculture\Phase2_Round2_Backups\bihar_agriculture_pre_v2_20261115-202553.archive.gz` |
| After verified V2 writes | `D:\BiharAgriculture\Phase2_Round2_Backups\bihar_agriculture_post_v2_20261115-210130.archive.gz` |

The pre-write backup contains the original database state. The post-write backup contains 7,713 mandi prices, 4,372 crop statistics, 221 agriculture documents and 42 mandi locations.

## 8. Automated verification

| Check | Result |
|---|---:|
| Focused V2 ingestion tests | 17/17 passed |
| Full repository regression suite | 215/215 passed |
| `pip check` | No broken requirements |
| Portable dump validation | 12,348/12,348 valid |
| `git diff --check` | Passed |

The full-suite console also prints an intentional `FileNotFoundError` for a missing-PDF negative test. The test asserts that this failure is reported correctly; the suite ends with `OK` and process exit code 0.

## 9. Examiner-side verification commands

### Collection and run counts

```cmd
docker exec bihar-mongodb mongosh --quiet --eval "const d=db.getSiblingDB('bihar_agriculture'); printjson({collections:{mandi_prices:d.mandi_prices.countDocuments({}),crop_statistics:d.crop_statistics.countDocuments({}),agriculture_documents:d.agriculture_documents.countDocuments({}),mandi_locations:d.mandi_locations.countDocuments({})},round2Runs:{json_mandi:d.mandi_prices.countDocuments({extraction_run_id:'1adcd0d4-e8a3-4e52-90dc-db34badb1e31'}),excel_crop:d.crop_statistics.countDocuments({extraction_run_id:'fb210766-bd5b-4ab7-a228-5f6c7150fd25'}),scanned_makhana_ocr:d.agriculture_documents.countDocuments({extraction_run_id:'4812ab68-154b-4406-bc93-5b63b74eed48'}),annual_scheme:d.agriculture_documents.countDocuments({extraction_run_id:'273c1179-cba9-4197-bb81-f556e069232d'}),horticulture_brochure:d.agriculture_documents.countDocuments({extraction_run_id:'544bc510-e019-4ea0-8b44-bade13617143'})}})"
```

### Excel source-to-Mongo comparison

Open `Excel_crop_area_production_yield.xlsx`, sheet `Bihar crops`, row 7. In MongoDB, query one record from run `fb210766-bd5b-4ab7-a228-5f6c7150fd25` and compare its `field_provenance` with cells A7, B7, C7, H7 and M7.

### Scanned-PDF source-to-Mongo comparison

Open page 1 of `ScannedPDF_makhana.pdf`. Query a document from run `4812ab68-154b-4406-bc93-5b63b74eed48` and display `page_number`, `chunk_index`, `extraction_method`, `content` and `field_provenance`.

### Portable dump validation

```cmd
python db\load_dump.py --validate-only
python -m unittest discover -s tests
```

## 10. Honest limitations and pending Round-2 work

The V2 foundation resolves unknown-file routing, mapping, provenance, safe persistence and quantitative run evidence. It does not make every extracted character perfect.

- OCR text is substantially improved but may still contain errors in charts, small numerals and stylized glyphs.
- Multi-column brochure reading order remains imperfect; brochure chunks are therefore stored as retrievable narrative evidence, not silently converted into structured numeric facts.
- The current evidence covers the five supplied surprise files. Broader adversarial-format testing should continue.
- Model-assisted Hindi/English normalization, weekly/monthly report presentation, district-trend views and OpenStreetMap integration remain separate follow-up workstreams.
- Rishi's existing ReAct layer remains untouched and independently demonstrable.

## 11. Conclusion

The Round-2 implementation converts the earlier “file was read” behaviour into an auditable ingestion lifecycle: inspect, extract, propose a schema mapping, enforce canonical contracts, quarantine failures, persist only validated records and retain exact source provenance. The final five-file rehearsal achieved **158/158 validated persisted outputs**, a clean 215-test regression suite and a reproducible 12,348-record portable dump.
