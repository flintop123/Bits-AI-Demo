# Viva from the local dashboard

Start the normal dashboard service before the session, with local MongoDB
and Ollama available. Open the loopback URL printed by `data_api.py`.
These features are not in the static GitHub Pages snapshot. During the
demo, the following actions all take place in the dashboard.

## Show ReAct

1. Open **Ask the data**, choose **ReAct agent** in **Workflow**, and
   enter a question about stored evidence in English or Hindi.
2. Show the actual tool invocation next to the grounded response. Open a
   citation and, if needed, inspect the retrieved evidence.

ReAct resolves the request and uses the local model to call its one
read-only tool. The answer and sources shown come from that tool. If
ReAct declines or does not call it, the UI reports that outcome rather
than inventing a tool invocation. **Direct QA** remains a separate mode.
For a new document, use the upload flow, not the ReAct question box.

## Ask Document Chat about indexed reports

Choose **Ask the data → Document Chat · local reports**. The existing
Jeetendra LangGraph workflow is reused with the dashboard’s local MongoDB
text index instead of its cloud-backed Milvus connector. This mode uses
loopback MongoDB and Ollama only; it does not use a cloud token, modify an
index, or sync data. It does not search new PDF uploads or report live
market prices. Use **Ask this PDF** for a saved upload and **Direct QA**
or **ReAct agent** for mandi prices and structured crop statistics.

When **Direct QA** or the dashboard’s **ReAct agent** handles an indexed
report question, it uses the same Document Chat evidence workflow. ReAct
still has to call its read-only tool before showing an answer. If the
document lookup has no verified evidence or is unavailable, it does not
substitute a legacy report answer. The standalone CLI, legacy API, and
upload/ingestion controls keep their original behavior.

The local model proposes English and Hindi search variants, including
translations beyond the reviewed vocabulary list. Named schemes also get
precise identifier searches, including reviewed acronym equivalents such
as PMFME/पीएमएफएमई. Candidate passages are ranked together; a similar
number in an unrelated scheme is not evidence. The dashboard creates
numbered excerpts from the top passages; the model selects IDs rather than
transcribing quotations. The dashboard validates those IDs and shows the
source text in its original language with page and chunk locators.
Generated summaries are labeled separately. If the first pass does not
produce a publishable summary, one optional local call can render only the
selected excerpts in the requested language within the existing time
budget. If that fails, the original citations still appear. Unsupported
numbers or recognized amount-unit changes are withheld. An explicitly
stated INR amount may use different digit grouping or lakh/crore notation
if its exact rupee value matches the selected source; plain numbers and
percentages cannot borrow that equivalence. These checks do
not establish that every statement in a generated explanation follows from
the source.

Try **“How many districts are in the organic farming corridor in the
Bihar Annual Scheme report?”**. In the stored 2022–23 report, physical PDF
page 14 describes 13 districts. Ask **“बीएआईपीपी पुस्तिका के अनुसार
पीएमएफएमई में खाद्य प्रसंस्करण इकाई के उन्नयन के लिए वित्तीय सहायता
कितनी है?”** and select Hindi for a Hindi explanation with an unchanged
English source excerpt (physical PDF page 11). **“Where does the APEDA
report say makhana is mainly cultivated in Bihar?”** is the reverse
English-to-Hindi-source check (physical PDF page 11). Verify the cited
pages. Search omissions or unavailable services are not a reason to run
an ingestion job, rebuild an index, or use a cloud credential.

## Examiner walkthrough: unseen PDF to verified evidence

1. Open **PDF upload**. Select the examiner's PDF, up to 10 MiB and
   25 pages. Use **Force OCR for a scan** if you need to demonstrate OCR.
2. Select **Extract and preview**. Show the page and
   chunk, extraction method, and validation counts. Select **Inspect
   source** to compare the extracted passage with a highlighted original
   page. An **exact excerpt** is only a verified part of the passage.
   **Page only** means the app could not prove a location on the page;
   this is always the case for OCR-derived chunks. Preview writes nothing
   to MongoDB. Optionally select **Run ReAct preview** to run the existing
   document source agent in dry-run mode on those same staged bytes. The
   result shows the actual tool call and extracted page, OCR and passage
   counts. It does not save anything or replace the reviewed preview.
3. Select **Save to MongoDB**. The page shows the verified read-back count.
   Expand **Run ID, fingerprints and audit details** for the run ID,
   collection, and source and read-back checksums. The server saves
   the reviewed passages from its draft, not text submitted by the
   browser, and verifies the returned record count and hash. Identical
   PDF bytes reuse the original saved run, even if the file was renamed.
   A different scan, edit, or re-export may have a new fingerprint.
4. Use **Ask this PDF**. For a reviewed table, ask for one crop or row and
   the metric and year. Try “बिहार में 2024–25 में गेहूँ का उत्पादन कितना था?”
   with **Table answer language → English**. The answer uses the saved,
   read-back-verified table (no Ollama call) and **View exact source cell**
   opens the original highlight. Unsupported or ambiguous table requests
   do not fall back to OCR numbers. For prose, the app shows checked
   verbatim quotes from extracted text when available, not translations.
   The exact quote is highlighted only if it can be located in the PDF.
5. To demonstrate persisted records after refresh, open **Reopen a saved
   upload**, paste the run ID, and select **Read from MongoDB**. The
   PDF bytes are not stored in MongoDB. If the temporary source cache is
   gone, **Verify and attach** accepts only the same original bytes.
   **Download verified evidence** exports the saved passages, coordinates,
   checksums, and table evidence as JSON; it does not include the PDF.

## What ReAct preview calls

The dashboard reuses Rishi’s LangChain factory. The bound preview tool calls
the same `AgricultureDocumentsSourceAgent` as the ReAct CLI’s
`ingest_agriculture_documents` tool, but not the CLI wrapper itself: that
wrapper reads the official-source manifest and may fetch files even in dry
run. Here the server supplies exactly one already validated local PDF from
the current draft, verifies its SHA-256, stages that immutable file in a
private temporary directory and forces `dry_run=True` in Python. The model
receives no PDF text or filename and cannot choose a path, URL, source set
or write mode. Ollama must be on loopback. The core extractor’s local
Tesseract fallback still applies. No database or remote download is required
for this action. Save remains a separate browser action after review.

## Show one exact table cell

The official Bihar DES final estimate and Annual Scheme PDFs match
checked-in, reviewed profiles. When those exact PDFs are uploaded,
**Verified table cells** lists row, column, value, unit and report context.
For example, on DES page 3, highlight **Wheat → Production (MT) →
7,826,998 MT**. A different PDF can still show passage evidence; it does
not get a verified table claim without a matching reviewed profile.

The side-by-side inspection follows the source-region pattern in
[Microsoft Document Intelligence](https://learn.microsoft.com/azure/ai-services/document-intelligence/prebuilt/layout)
and [Google Document AI](https://docs.cloud.google.com/document-ai/docs/reference/rest/v1/Document).
The answer-to-source action follows
[NotebookLM's inline citation approach](https://blog.google/innovation-and-ai/products/notebooklm-goes-global-support-for-websites-slides-fact-check/).
Uploaded PDFs are processed locally by AgriAgent, not sent to these products.

The default MongoDB location is
`bihar_agriculture.viva_document_uploads`, separate from the curated
`agriculture_documents` corpus. The upload does not change normal QA's
search results or the distributed data snapshot. All validated passages
in one run are stored together. The saved run ID for a new PDF is derived
from its SHA-256 so concurrent saves cannot append another run for the
same bytes. An earlier saved record is reused without rewriting it; any
duplicates saved before this update remain untouched. A preview or temporary
image source can expire after 30 minutes, when the process restarts, or
when newer uploads fill the cache.

The preview uses the existing PDF text/OCR extractor and a fixed schema
for document passages. Table facts require the separately verified profile
described above. The system does not infer whether an unseen document is authoritative. Only
upload material you can retain locally as extracted text. There is no
browser delete or public upload operation.
