# Challenge and Supporting Literature

## 1. Problem being addressed

The project is not simply a chatbot over one clean dataset. Bihar agriculture information arrives in several incompatible forms: a live Hindi mandi table, a long-running Excel workbook, English born-digital PDFs, and scanned Hindi PDFs. A useful system must preserve numbers, units, dates, locations, page references, source URLs and extraction history while still supporting natural-language questions.

This creates four practical problems:

1. one parser cannot reliably handle every source format;
2. scanned pages require OCR, while born-digital pages should retain their embedded text;
3. repeated ingestion must update or match existing records instead of creating duplicates; and
4. a generated answer must be traceable to retrieved database records or document pages.

The work therefore treats extraction, storage, retrieval and answer generation as separate, testable stages.

## 2. Approaches considered

### 2.1 One general-purpose agent versus specialist agents

ReAct showed the value of interleaving reasoning and external actions for tasks where the next information source must be discovered during execution [1]. That is useful for open-ended research, but our current source types are known in advance. Asking a language model to rediscover whether a file is a workbook, a web table or a PDF would add latency and a new failure mode without improving routing accuracy.

We therefore selected deterministic source-type routing with three specialist agents:

| Input | Specialist | Main tool | Why fixed routing is used |
| --- | --- | --- | --- |
| Hindi mandi web table | `mandi_web_agent` | Playwright | The page and expected table fields are known. |
| Crop statistics workbook | `crop_statistics_excel_agent` | pandas/openpyxl | Workbook structure requires explicit sheet and row normalization. |
| English/Hindi PDF | `multilingual_pdf_agent` | pypdf with Tesseract fallback | Extraction method depends on whether usable embedded text is present. |

The supervisor still records selection, status, tool calls, retries, results and completion. A more exploratory ReAct-style router remains a future option for unseen source types.

### 2.2 Format-aware extraction versus converting everything to plain text

pandas documents `read_excel` and its openpyxl engine for `.xlsx` files [2]. We use this structured route because it preserves rows, columns and numeric values before normalization. Flattening the workbook into text would make field validation, unit handling and duplicate identity less reliable.

pypdf explicitly distinguishes text extraction from OCR: image-only pages may contain little or no extractable text, so OCR software such as Tesseract is needed [3]. The PDF agent therefore attempts direct extraction first and invokes Hindi/English OCR only when the direct text is insufficient. This avoids unnecessary OCR on born-digital pages while supporting scanned Hindi documents.

Tesseract's own documentation notes that resolution, noise, skew and page segmentation influence recognition quality [4]. OCR output is consequently treated as extracted evidence, not as a perfect transcription. Page number, detected language, extraction method and source URL are retained so a reviewer can inspect the original page.

### 2.3 Grounded retrieval versus answering from model memory

The RAG paper combines generation with retrieved non-parametric memory [5]. Our implementation follows the same practical principle: retrieve project data first, then ask the local model to answer only from the supplied context. The system returns source metadata with the answer. It does not claim that the local Qwen model independently knows current Bihar agriculture facts.

For this phase, document retrieval uses MongoDB text search. MongoDB states that text indexes support word-based `$text` queries, but its current documentation recommends Search or Vector Search for more advanced full-text and semantic retrieval [6]. This is an explicit boundary: the current implementation supports lexical evidence retrieval; semantic and hybrid retrieval are future work.

### 2.4 Duplicate-safe writes and provenance

MongoDB compound unique indexes enforce uniqueness over a combination of key values [7]. The project applies compound identities appropriate to each collection and performs upserts. This makes repeated ingestion measurable and duplicate-safe. Each persisted record also stores `extraction_run_id`, `extracting_agent`, `source_type` and `extracted_at`, alongside source-specific fields.

### 2.5 Agent evaluation and observability

AgentEvals trajectory matching checks an actual sequence against an expected sequence and supports strict, unordered, subset and superset modes [8]. We use deterministic trajectory matching because the expected source-to-agent-to-tool path is known. LangSmith traces provide the complementary execution record: supervisor output, child tool run, inputs, outputs and status. LangSmith's evaluation guidance also distinguishes rule-based unit checks, regression evaluation and online monitoring [9].

## 3. What was tested and learned

The figures below are outputs from committed evidence files and repeatable test commands, not estimates.

| Area | Observed result | Interpretation |
| --- | ---: | --- |
| Mandi extraction | 10 records | Hindi table parsing and price normalization work on the current page. |
| Crop workbook | 4,372 records; 36 crop groups; 1966-67 to 2024-25 | Structured Excel parsing preserves a long time series. |
| Multilingual PDF run | 72 of 75 pages extracted | Mixed direct-text and OCR processing works, with three pages explicitly skipped. |
| PDF extraction method | 40 direct-text pages; 32 OCR pages | The fallback is exercised in practice, not only implemented. |
| Searchable PDF output | 153 chunks; 171,306 characters | Page-aware evidence is available for retrieval. |
| Agent evaluation | 3 of 3 agents passed | Expected tool trajectories matched for all current specialists. |
| Automation | 3 of 3 sources; 100%; 0 retries | The complete recorded run required no manual intervention after launch. |
| Database provenance | 10/10, 4,372/4,372 and 153/153 records | Every record in the three populated collections contains run and agent provenance. |
| Automated tests | 53 passing before this literature addition | Extraction, API, QA, orchestration, evaluation and schema behaviours are covered. |

The most important finding is that multilingual support is not a single translation step. Hindi web text can be read directly from the DOM, while scanned Hindi PDFs require OCR and quality checks. The hybrid direct-text/OCR approach is therefore retained.

The second finding is that fixed routing is appropriate at the present scope. It produced a complete three-agent run with no retries, and the trace is easy to explain during evaluation. Model-based routing would become justified when users can introduce unregistered sources or ambiguous tasks.

The third finding is that provenance must be written during ingestion. Adding citations only when the answer is generated would not be sufficient because the database record itself would have no auditable extraction history.

## 4. Current limitations

- Three of 75 requested PDF pages produced no accepted text in the recorded multilingual run. Image preprocessing, OCR confidence thresholds and page-specific review are still required.
- The mandi parser depends on the current website table structure. A layout change may require selector or header updates.
- The Excel parser is designed for the submitted crop-statistics workbook. It validates that layout rather than pretending to parse arbitrary spreadsheets.
- MongoDB `$text` retrieval is lexical. Hindi inflection, spelling variants and semantically related wording may not retrieve the best chunk.
- Qwen3 4B runs locally and keeps the demonstration inexpensive and reproducible, but answer quality is bounded by a small model and retrieved context.
- Current trajectory evaluation proves the expected routing and tool use; it does not by itself prove factual correctness of every generated answer.
- LangSmith upload requires a configured key. Local JSON traces and AgentEvals remain available when the key is absent.

## 5. Decision summary

The selected design is a deterministic supervisor with format-specific extraction agents, duplicate-safe MongoDB storage, explicit provenance, retrieval-grounded local generation, and both offline and traced evaluation. This design is narrower than a fully autonomous research agent, but it matches the sources currently available and produces inspectable evidence for each stage. The next technical priority is improving retrieval quality and building a labelled bilingual QA set, not adding unconstrained agent autonomy.

## References

1. Yao, S. et al. (2022). *ReAct: Synergizing Reasoning and Acting in Language Models*. https://arxiv.org/abs/2210.03629
2. pandas documentation. *IO tools: Reading Excel files*. https://pandas.pydata.org/docs/user_guide/io.html#reading-excel-files
3. pypdf documentation. *Extract Text from a PDF*. https://pypdf.readthedocs.io/en/stable/user/extract-text.html
4. Tesseract OCR documentation. *Improving the quality of the output*. https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html
5. Lewis, P. et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. https://arxiv.org/abs/2005.11401
6. MongoDB documentation. *Text Search*. https://www.mongodb.com/docs/manual/text-search/
7. MongoDB documentation. *Create a Compound Unique Index*. https://www.mongodb.com/docs/manual/core/index-unique/create-compound/
8. LangChain. *AgentEvals: Readymade evaluators for agent trajectories*. https://github.com/langchain-ai/agentevals
9. LangSmith documentation. *Evaluation types*. https://docs.langchain.com/langsmith/evaluation-types

Accessed 18 October 2026.
