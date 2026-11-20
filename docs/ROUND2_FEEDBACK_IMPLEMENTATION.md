# Round 2 feedback: what to demonstrate and what remains

This work extends the existing ingestion-v2 and localhost dashboard on top of
the PDF table extractor. It does not change Rishi's ReAct layer, activate new
live sources, or change the default dry-run behavior.

## Maps, search radius, and district trends

On the localhost dashboard, the live marker map now uses Leaflet/OpenStreetMap.
The status shows whether map tiles have loaded; if the Leaflet library is
unavailable, the original coordinate-only plot is used. If only the tiles
fail, verified markers remain visible on a blank basemap. The nearby search
draws its returned centre and radius and highlights the returned market points.

Use **Use verified Arwal demo point**: latitude `25.24324`, longitude
`84.662895`. The saved source is the Arwal locality centroid, market code
`1635`, not a surveyed gate. Compare **1 km** with **75 km** using the same
crop filter. Check the browser tile status, one marker popup, the radius
overlay, and which markets were returned. Distances are straight-line.
The 365-calendar-day price window is anchored to the latest matching date
in the data, and results are capped at 100 observations. Therefore larger
radius responses need not contain every row returned at the smaller radius.

With the local API running, verify the response coordinates and distances
without relying on the browser display:

```cmd
python scripts\verify_round2_radius.py --latitude 25.24324 --longitude 84.662895 --small 1 --large 75 --expect-market-code 1635
```

The verifier separately reports whether a market outside the smaller radius
was returned. Add `--require-expansion` only when checking a demo that must
show an additional market. Its result is not evidence that tiles loaded.
The saved Phase 5 evidence contains an Arwal 5 km query; do not present
the new 1/75 km live run as passed before checking it.

**District trends** is a separate live dashboard section. Pick a district and a
crop, then choose daily, weekly, or monthly. Results come from the existing
MongoDB aggregation, use observed prices only, and keep different units
separate. Empty periods are not fabricated, and the newest period can be partial.

## Intake of weekly and monthly summary files

The two report previews accept UTF-8 district report CSVs from the documented
export contract; they do not populate `mandi_prices` or pretend aggregated
prices are daily observations. The matching view validates calendar boundaries,
frequency, unique district/crop/unit/period keys, observed counts, and
nonnegative prices, and shows the file hash and CSV line for review.

To generate examples from the maintained snapshot, use distinct output names:

```cmd
python scripts\export_mandi_period_report.py --frequency weekly --output "%TEMP%\round2-weekly.csv"
python scripts\export_mandi_period_report.py --frequency monthly --output "%TEMP%\round2-monthly.csv"
```

Load them into the matching views, then deliberately try the weekly CSV in
the monthly view. Generated reports demonstrate the round trip for the known
export contract, not support for arbitrary third-party weekly/monthly layouts.
The preview does not store the uploaded file, query MongoDB, or call a model.

## Field accuracy, live ingestion, and provenance

A successful insert or schema check does not show that the right fields were
captured. Review 10–15 fields per surprise file directly against the source.
Create a JSON manifest containing `source_sha256`, `target_collection`,
and `records`. Each record has its exact target identity and a `fields`
dictionary whose entries contain a reviewed scalar `value`, a human-readable
`source_location`, and, optionally, the exact keys to check in
`expected_locator`.

| Collection | Identity keys for the manifest |
| --- | --- |
| `mandi_prices` | `source_record_id`, `date` |
| `crop_statistics` | `crop`, `season`, `year` |
| `agriculture_documents` | `source_url`, `page_number`, `chunk_index` |
| `mandi_locations` | `market_code` |

For example, a field entry might be
`"price":{"value":1200,"source_location":"JSON $[14].price","expected_locator":{"json_path":"$[14].price"}}`.
Take expected values from the source, not the saved mapping. The source bytes,
review key, and recorded run must all agree on SHA-256.

```cmd
python run_ingestion_v2.py --input "path\to\source.json" --progress
python -m ingestion_v2.field_accuracy --run-dir "artifacts\ingestion_v2\<run-id>" --source "path\to\source.json" --manifest "path\to\review-key.json" --html "%TEMP%\round2-field-accuracy.html"
```

`--progress` streams stage start/result events to the terminal while processing;
the same events are saved in `events.jsonl`. The audit reports
correct, wrong, missing, ambiguous and not-checked fields separately for mapped
and stored results; expected-field and checked-field denominators are explicit.
The HTML view puts reviewed source locations, mapped fields, stored fields and
the process log side by side. Keep the original file open at the cited location.
For an **existing saved write run**, add `--verify-mongo` to the audit for
read-back only. A dry run is not evidence of a MongoDB write, and an unsampled
record is not treated as missing. Prefer a read-only MongoDB account.

JSONPath and Excel sheet/cell evidence are unchanged. PDF source locators now
include literal numbered headings when the heading can be tied to the same
chunk. Semantic quotes that span headings, or have no exact offsets, are not
given a guessed section. The reviewed PDF-table path remains read-only. It
does not establish OCR table extraction or automatic layout mapping for every
unseen report.

## Tool schemas, translation, formats, and LoRA

- `python run_ingestion_v2.py --print-tool-schemas` exports registered
  **ingestion-v2** tool contracts. This does not claim schema coverage for
  the whole legacy app or modify its ReAct tools. AI proposes unfamiliar
  schema mappings and grounded facts; validation and write controls stay explicit.
- `python -m scripts.verify_bilingual_intake --key "<reviewed-label-key.json>"`
  checks model-assisted Hindi/English labels against an independent review
  key. Add `--lookup-only` for the alias-only comparison. An alias or a human
  approval cannot be counted as an accepted model label.
- `python run_ingestion_v2.py --list-formats` lists the formats the ingestion
  path actually accepts. **Word conversion is not implemented**: this is not a
  PDF-to-DOCX converter, and it does not ingest DOC/DOCX. The original question
  about supported formats is now answerable without guessing a conversion
  direction or claiming unsupported functionality.
- `python scripts\summarize_adapter_comparison.py` reads the checked-in
  per-case results. **2/10 and 4/10** are counts of correctly routed QA intents
  on the same ten held-out examples for FLAN-T5-small before and after the
  intent-router LoRA adapter. Of the ten, two improved, none regressed, and
  six were wrong under both. This is **not** deployed Qwen accuracy or a
  full-answer score. The script summarizes recorded results; it does not rerun
  or independently attest to training.

## Pending source mappings

`python review_pending_source.py --list` gives the four source IDs, local
sample formats, and acceptance gates. Supply an authentic export when
available and use the existing preflight with `--source`, `--sample`,
`--sha256`, and a reviewed `--plan` when applicable. A hash pins the
reviewed file bytes; it is not proof of origin by itself.

| Pending source | What still needs real evidence |
| --- | --- |
| Bihar State Data Lab | Validate an authentic structured export and its estimate type, periods, geography, and units. The reviewed DES PDF tables cover only their pinned PDF. |
| Bihar Horticulture dynamic datasets | Identify and verify a live export; the brochure is not validation of a dynamic dataset. |
| Bihar State Seed Certification reports | Obtain the report inventory and inspect authentic, source-located samples. |
| NASA AppEEARS/MODIS | Validate authentic products, spatial reference, bands, units and quality masks. A container signature does not establish spatial correctness. |

Do not switch any of these sources to active based on a local synthetic preflight.
