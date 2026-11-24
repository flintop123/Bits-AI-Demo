# Optional Milvus Vector RAG dashboard mode

This local demo sends the fixed public organic-farming-corridor question as a
dense vector to an explicitly chosen Zilliz collection. It passes only
allowlisted original Annual Scheme passages to local Ollama, with physical PDF
page and chunk citations. It reuses the existing Milvus retrieval and final
answer nodes with a scoped connector. It does not change Direct QA, ReAct,
Document Chat, the normal server, the team configuration, or MongoDB indexes.

Prerequisites: the project's Python environment, local Ollama on
`127.0.0.1:11434`, and already installed `bge-m3` and `qwen3:4b` models.
Use only an endpoint, collection, and appropriate token approved by their
owner. Each command requests the token via hidden interactive entry. Do not
put it in CMD, a chat, the project files, or a recording. Do not use a
previously committed secret. Remove the token from sight before recording.

## Existing approved collection (no upload)

The existing collection must already be loaded by its owner and have the
teammate sync's dense BGE-M3 COSINE index, `embedding`, `source`,
`text_content` (serialized JSON), and JSON `metadata` containing
`mongo_collection`. It must contain the exact reviewed public Annual Scheme
passages: the connector rejects changed text, missing source locators or
other documents. A different vector dimension, indexing model, schema, or
older corpus is not silently supported. No load, write, or fallback is
performed against a shared collection.

From Windows CMD in the repository (replace the endpoint and collection
placeholders with those explicitly approved by the owner):

```bat
.venv\Scripts\python.exe milvus_public_demo.py serve --endpoint "https://YOUR-APPROVED-ENDPOINT.zillizcloud.com" --collection "YOUR_APPROVED_COLLECTION" --shared-read-only
```

Open **http://127.0.0.1:5008/** → **Ask AgriAgent** → **Example questions** →
**Milvus Vector RAG: organic farming** → **Ask**. Or choose the mode and enter
“What does the report say about the organic farming corridor?” in English.
The mode accepts only this public demo question, with English or Automatic
language, to prevent sending arbitrary user prompts as cloud embeddings.
The `ask` command can replace `serve` for a terminal test. If generation
fails or does not have valid citations, the original retrieved passages are
shown instead; a generated answer is not claimed. Verify any generated
phrasing against the original source.

## Alternative: seed a new isolated collection (upload)

Preview first. This default operation neither asks for credentials nor contacts
any service. Add `--show-passages` to inspect the exact allowed text.

```bat
.venv\Scripts\python.exe milvus_public_demo.py
```

Only if the owner has authorized uploading the 54 reviewed public passages and
their vectors into this Zilliz account, use the fresh name printed by preview:

```bat
.venv\Scripts\python.exe milvus_public_demo.py seed --endpoint "https://YOUR-APPROVED-ENDPOINT.zillizcloud.com" --collection "PASTE_FRESH_NAME_FROM_PREVIEW" --approve-public-upload
```

Nothing from live MongoDB is read or sent. Only exact public text, its vector,
the official URL, and public PDF page/chunk locators with synthetic keys are
sent. Seeding refuses any existing collection; it cannot update or delete an
existing collection. If a partial/uncertain write occurs, let its owner
inspect it and use a new name rather than retrying into it. Then launch with
`serve`, the same endpoint and new collection, without `--shared-read-only`.

Normal `data_api.py` stays unchanged in behavior and does not offer the
Milvus mode. Start the opt-in server on a separate port without stopping the
normal dashboard.
