
| Purpose | Words |
|---|---|
| **Question starts** (the first word only) | what, which, how, why, when, who, where, is, are, was, were, does, did, compare, क्या, कितना, कितनी, कौन |
| **Ingest verbs** (anywhere) | load, fetch, ingest, pull, update, refresh, download, index, extract, import, scrape, sync |
| **Mandi** | mandi, market price, मंडी |
| **Crop statistics** | crop statistic, crop stat, crop-wise, crop wise, crop area, area production, production, yield, फसल |
| **Documents** | document, scheme, policy, brochure, handbook, makhana, apeda, pmfme, horticulture, मखाना, दस्तावेज, योजना |
| **Format: api** | api |
| **Format: excel** | excel, xlsx, xls, workbook, spreadsheet |
| **Format: pdf** | pdf |

**Decision order**
1. If the first word is a question start, it's a question and goes to the question tool, even if an ingest verb is also present.
2. Otherwise it needs an ingest verb. Without one, a request containing `?` counts as a question, and anything else is unclear.
3. With an ingest verb, the domain and format words choose the source. One match resolves. Anything else opens the popup.

## Matching inputs
| Input | Result |
|---|---|
| `load last seven days of mandi data via api` | mandi API |
| `pull today's mandi prices` | mandi API, because mandi has only one source |
| `refresh crop statistics` | crop Excel |
| `load production and yield from excel` | crop Excel |
| `ingest the makhana handbook pdf` | PDFs |
| `मंडी का डेटा fetch करो` | mandi API |
| `load excel` | crop Excel, because a format alone can pick the source |
| `what was total rice production in 2024-25?` | question |
| `क्या बिहार में गेहूँ का उत्पादन बढ़ा?` | question |
| `mandi prices?` | question, because of the `?` |
| `how to load mandi data` | question, because "how" comes first |

## Non-matching inputs
| Input | Result and why |
|---|---|
| `hello` | unclear, popup shows all 4 options |
| `load crop data` | unclear, because bare "crop" isn't a keyword (use "crop statistics" or "production") |
| `bring in crop numbers` | unclear, because "bring" isn't an ingest verb |
| `upload the pdf` | unclear, because "upload" doesn't match "load" |
| `मंडी का डेटा लोड करो` | unclear, because there are no Hindi ingest verbs |
| `mandi prices` | unclear, no verb and no `?` |
| `show wheat yield` | unclear, because "show" isn't a verb |
| `load mandi data via excel` | unsupported, popup lists the 3 ingestion sources |
| `refresh production data via api` | unsupported, crop statistics only comes from Excel |
| `load mandi pdf` | unsupported, "pdf" is only a format word |
| `load mandi and production data` | ambiguous, two domains match |

These work from the project root with your venv active. They are for the current `run_extractor.py`, which takes an optional `--non-interactive` flag and the request text. There is no `--write` flag any more, so a run writes unless the request asks for a dry run.

On your Machine:
```bash
source .venv/bin/activate        # or call .venv/bin/python directly
```
Always put the request in quotes, because `?` and `'` are special in zsh.

**Ingest**
```bash
python run_extractor.py "load last seven days of mandi data via api"
python run_extractor.py "pull today's mandi prices"
python run_extractor.py "refresh crop statistics from excel"
python run_extractor.py "ingest the makhana handbook pdf"
python run_extractor.py "load hindi pdfs"
python run_extractor.py "ingest pmfme_makhana_handbook_hindi"      # a PDF source id from sources/agriculture_sources.yaml
```

**Dry run (validate only, no MongoDB write).** Any one of "dry run", "dry-run", "validate", "without writing", "no write", "don't write", "do not write" or "test only" in the text does it:
```bash
python run_extractor.py "dry run last 3 days of mandi data via api"
python run_extractor.py "validate crop statistics from excel"
python run_extractor.py "ingest makhana handbook pdf, dry run"
```
Watch for `dry_run=True` or `dry_run=False` in the "Tool result" line.


**Unclear requests**
```bash
python run_extractor.py "load some data"                   # prints numbered options; type a number, Enter to cancel
python run_extractor.py --non-interactive "load some data" # lists the options and exits without running anything
```
Use `--non-interactive` in scripts or cron so a run never waits for input.

**Checking what happened**
```bash
tail -f logs/agent_run.log          # every step: input, tool chosen, model reason, tool result
ollama list                         # qwen3:4b should be listed
```

**Before the first run**
- Ollama must be running with `qwen3:4b` pulled.
- MongoDB must be reachable. The default is `mongodb://localhost:27017/`, and `MONGODB_URI` overrides it.
- For the `mandi ... via api` request, Playwright needs its browser installed once: `python -m playwright install chromium`.

`python agent.py "<request>"` runs the same entry point, so use either one.