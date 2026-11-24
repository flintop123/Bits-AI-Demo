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
owner. By default the launcher requests the token via hidden interactive entry.
The optional personal-config launcher described below removes that prompt. Do not
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
placeholders with those explicitly approved by the owner). Use the precise
**Public Endpoint** shown in Zilliz Cloud; approved older GCP Serverless
endpoints ending in `.serverless.gcp-<region>.cloud.zilliz.com` also work:

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
shown instead; a generated answer is not claimed. The dashboard explains
whether the local model failed or its summary was rejected, without exposing
the draft or service details. In the terminal, `Generation check` shows the
same status. The displayed model answer must be one or two exact source
sentences with the citation. Drafting or reasoning text never appears.
Testing this mode does not change the collection or require reseeding.

## Optional: read the token from a personal config file each launch

Use a new least-privilege read-only credential approved for that collection.
Store it in `~/.agriagent/milvus-demo.json` outside every Git checkout. Do not
use the repository's `config.yaml`, make a link to it, or put this file in a
shared/synced folder. This file is plaintext protected by your account's
permissions. Do not commit, email, screen-share, or record it. Each launch
reads the current file; restart the launcher after rotating the token.

**Windows CMD** (your local profile access only; do not grant other users
permissions):

```bat
if not exist "%USERPROFILE%\.agriagent" mkdir "%USERPROFILE%\.agriagent"
notepad "%USERPROFILE%\.agriagent\milvus-demo.json"
```

**macOS/Linux terminal:**

```sh
(umask 077; mkdir -p "$HOME/.agriagent"; touch "$HOME/.agriagent/milvus-demo.json")
chmod 700 "$HOME/.agriagent"
chmod 600 "$HOME/.agriagent/milvus-demo.json"
nano "$HOME/.agriagent/milvus-demo.json"
```

In the editor, use these exact fields and replace the placeholders privately:

```json
{
  "endpoint": "https://YOUR-APPROVED-ENDPOINT.zillizcloud.com",
  "collection": "YOUR_APPROVED_COLLECTION",
  "token": "YOUR_FRESH_APPROVED_READ_ONLY_TOKEN"
}
```

From the project root, launch the local dashboard with the saved config:

```bat
.venv\Scripts\python.exe milvus_public_demo.py serve --local-config
```

```sh
.venv/bin/python milvus_public_demo.py serve --local-config
```

This flag works only for `serve`. A collection named `agriagent_demo_<12 hex>`
uses the seeded demo's passage layout; other approved collection names use
the shared sync layout described above. It never seeds, writes, or loads
either collection. The collection must already be loaded (the seed command
normally loads a new collection when creating its index). It cannot be
combined with connection flags. A missing, unsafe or malformed personal file stops startup;
there is no password prompt, environment-variable fallback or lookup of
project credentials in this mode. The browser never receives the token.

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
