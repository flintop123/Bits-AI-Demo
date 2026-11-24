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
