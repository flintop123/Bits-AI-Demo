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

## Show an unseen PDF entering MongoDB

1. Open **PDF upload**. Select the examiner's PDF, up to 10 MiB and
   25 pages. Use **Force OCR for a scan** if you need to demonstrate OCR.
2. Select **Extract and preview**. Show the extracted page and chunk,
   method, text, validation counts, and the source PDF hash. **Open source
   page** uses your browser's copy of the selected PDF. No database records
   are written at this step.
3. Select **Save to MongoDB**. The page shows the verified read-back count,
   run ID, collection, record hash and saved passages. The server saves
   the reviewed passages from its draft, not text submitted by the
   browser, and verifies the returned record count and hash.
4. To demonstrate persisted records after refresh, open **Reopen a saved
   upload**, paste the run ID, and select **Read from MongoDB**. The
   original PDF is not stored and must be opened separately after refresh.

The default MongoDB location is
`bihar_agriculture.viva_document_uploads`, separate from the curated
`agriculture_documents` corpus. The upload does not change normal QA's
search results or the distributed data snapshot. All validated passages
in one run are stored together, keyed by the run ID; a save retry cannot
append a second copy of that run. A preview can expire after 30 minutes,
when the process restarts, or when newer previews fill the draft cache.

The preview uses the existing PDF text/OCR extractor and a fixed schema
for document passages. It does not claim to identify numerical table
facts or infer whether an examiner's document is authoritative. Only
upload material you can retain locally as extracted text. There is no
browser delete or public upload operation.
