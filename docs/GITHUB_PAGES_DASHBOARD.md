# GitHub Pages evidence dashboard

The repository's `docs/` directory contains a static, bilingual dashboard for
the academic Phase II demonstration. It presents committed evidence and does
not imitate the live backend.

## Local preview

For the static snapshot alone, run from the repository root:

```powershell
python scripts\build_github_pages_snapshot.py
python -m http.server 8000 --directory docs
```

Open <http://127.0.0.1:8000/>. Stop the server with `Ctrl+C`.

### Enable unrestricted local questions

The page automatically detects the real local QA API on port 5000. Start both
processes in separate terminals:

```powershell
# Terminal 1: MongoDB and Ollama must already be available
python data_api.py
```

```powershell
# Terminal 2
python -m http.server 8000 --directory docs
```

Open <http://127.0.0.1:8000/>. The QA status changes to **Live local QA
connected**. Questions are sent to `http://127.0.0.1:5000/api/v1/ask`; the API
accepts cross-origin requests only from loopback HTTP origins.

## Publish with GitHub Pages

After this change is merged into `main`:

1. Open the repository on GitHub.
2. Choose **Settings → Pages**.
3. Under **Build and deployment**, select **Deploy from a branch**.
4. Select branch **main**, folder **/docs**, then click **Save**.
5. Wait for the Pages deployment to finish.

The expected project URL is:

<https://flintop123.github.io/Bits-AI-Demo/>

## Snapshot boundary

GitHub Pages hosts static files only. The hosted dashboard therefore reads
`docs/data/dashboard_snapshot.json`, which is generated from committed
validation evidence. Its Ask panel answers only the clearly labelled verified
demonstration questions. Live Bihar mandi ingestion, MongoDB queries, local
Qwen3 answer generation, bge-m3 embeddings and Tesseract OCR remain part of the
local application demonstrated from the repository.

Regenerate the snapshot whenever the committed evidence changes:

```powershell
python scripts\build_github_pages_snapshot.py
```
