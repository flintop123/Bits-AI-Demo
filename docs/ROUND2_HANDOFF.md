# Bihar AI assignment: Round 2 handoff

This integrated patch applies to semantic PDF commit `9046fa3`. It brings
across the observability work from `ea663a7` and the Round 2 changes, keeping
the semantic PDF and evidence commands in one CLI. The ReAct entry point
was not changed. Nothing was pushed or written to MongoDB.

| Feedback | What to use | What still needs verification |
| --- | --- | --- |
| Correct mapping; show source, mapping, Mongo and events together | `run_ingestion_v2.py --report-run RUN_ID --verify-mongo`. Joins by source locator, never row order. It visibly separates unverified or differing values from matched rows. | On your laptop, inspect three matched rows against original files and check any discrepancy by field. Match counts are not extraction accuracy. |
| Exact PDF tags and unfamiliar layouts | Use the blinded extraction review from the earlier attachment and the semantic PDF dry run. Quote-anchored fact results are in `semantic_facts.json`; the standard mapping report is separate. The HTML report displays exact character offsets or a bounding box when the extractor supplies them. | No live Ollama run on the annual-schemes PDF has been verified here. Test with a reviewed plan first; separately test an authentic unfamiliar layout without a preselected plan. Run an independent 10–15 field answer-key comparison rather than taking schema validity as accuracy. |
| Less deterministic reasoning; leave ReAct alone | `review_ingestion_plan.py` performs one proposal and one structured challenge through the configured model. It evaluates alternative mappings and flags disagreement, low confidence, static values and warnings. It cannot persist. | Test on a novel input locally. The same model can agree with itself and still be wrong. Keep an independent answer key. |
| Hindi-English normalization | Ported bilingual branch `021a2a7`. `scripts/verify_bilingual_intake.py` compares labels against a separately reviewed key and distinguishes alias lookup from model inference. | Run with a genuine held-back Hindi source and your configured local model. |
| Tools with explicit schemas | Existing `python run_ingestion_v2.py --print-tool-schemas` still exports ingestion contracts. The standalone challenge has a separate structured review contract and receives no database tool. | Show schemas and the recorded outcome in the demo; do not replace the pre-existing ReAct workflow. |
| Pending data sources | `review_pending_source.py` checks sample shape, content hash and representative locators. Three Bihar routes support reviewed canonical mapping; the NASA route checks TIFF/HDF signature only. | Authentic samples, current endpoints, NASA spatial validation and live ingest remain open. Routes are still marked pending. |
| Weekly/monthly reports, district trends and OSM | Dashboard, read-only API, CSV exporter and Windows scheduler wrapper; see `TEMPORAL_SPATIAL_DASHBOARD_V2.md`. | Verify against live MongoDB and map tiles; the wrapper was not run on Windows and no task was installed. |
| Phase III live demonstration | `eval/round2_demo_README.md` and `eval/round2_demo.py` supply ten expected-answer checks and a read-only live DB mode. | Run through the live system and compare with original sources. Check the current demo slot and evaluated tag in Nalanda. |

## Start with these checks

From the repository root, using the project's existing Python environment:

```cmd
python -m unittest discover -s tests -p "test_round2*.py" -v
python eval/round2_demo.py
python run_ingestion_v2.py --print-tool-schemas
```

Read-only laptop checks, using a fresh output filename:

```cmd
python eval/round2_demo.py --live --output phase3_live_demo.json
python run_ingestion_v2.py --report-run YOUR_EXISTING_RUN_ID --verify-mongo
```

The command below uses a reviewed plan and does not write to MongoDB:

```cmd
python run_ingestion_v2.py --input "D:\BiharAgriculture\Phase2_Round2_Inputs\PDF_annual_scheme_agriculture.pdf" --plan "%TEMP%\agriagent-annual-pdf-plan.json" --semantic-facts --max-fact-chunks 4 --fact-batch-size 2
```

For an unfamiliar file, omit the reviewed plan when you want to test whether
the model can choose the route. First review the file independently and
freeze your expected fields. Business/source validation is separate from
schema validity. Do not use `--write` merely to make the evidence appear
complete.
