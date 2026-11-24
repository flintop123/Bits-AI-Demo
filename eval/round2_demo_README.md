# Phase III: ten query rehearsal

Use the ten queries below to rehearse against a fixed dataset. The checked-in
`db/dump/` JSONL at `ea663a7` is the evidence baseline; the market questions
deliberately use fixed October 2026 dates, not "today". This check measures
database answers, not language-model accuracy, live agent behaviour or an
official evaluation result. It does not verify the content against the original
publisher unless a human also opens the cited source.

| ID | Type | Live demo question | Expected answer on the pinned dump |
| --- | --- | --- | --- |
| Q01 | Spatial: district + market | What was the modal potato price in Arwal market, Arwal district, on 17 Oct 2026? | Local, ₹1,200/quintal. |
| Q02 | Spatial: verified radius | Which verified mandi locations lie within 1 km of 25.24324° N, 84.662895° E? | Arwal, official market code 1635; OpenStreetMap Nominatim locality centroid, not a verified facility entrance. |
| Q03 | Temporal: daily | Show Arwal potato observations for 15–17 Oct 2026, date, variety and price in chronological order. | 15 Oct Local ₹1,100; 16 Oct Desi ₹1,250; 17 Oct Local ₹1,200, all per quintal. The varieties are not fixed, so do not describe this as a like-for-like price trend. |
| Q04 | Temporal: annual | Show stored Kharif rice production for 1966–67 through 1968–69. | 1,445,200; 4,531,600; 4,997,400 tonnes, respectively. |
| Q05 | Provenance: Excel row | Trace 1966–67 Kharif rice yield to the workbook and row. | 329 kg/hectare, `Crop wise Area Production & Yield.xlsx`, row 8. |
| Q06 | Provenance: PDF page/chunk | Find the 2022–23 Agriculture and Allied Scheme outlay and quote its source row. | 505,133.00 lakh (5.05%); Bihar Annual Scheme 2022–23, PDF page 11 (printed page 7), chunk 0. |
| Q07 | Bilingual/OCR | मखाना निर्यात की कार्यनीति के शीर्षक का मूल हिन्दी पाठ, PDF पृष्ठ और निष्कर्षण विधि दिखाएँ। | “भारत से मखाना निर्यात को प्रोत्साहित किए जाने हेतु कार्यनीति”; APEDA Hindi PDF page 2, chunk 0; Tesseract OCR. |
| Q08 | Provenance: official API row | Trace the Arwal Local potato observation on 17 Oct 2026 to its source record and run. | Bihar Krishi mandi API; record `08b070d1-1de3-4da5-b01e-b3f666530eca`; run `35958d0f-fdcf-49db-b48e-06e99e6d14dc` on the pinned dump. |
| Q09 | Comparison: same market/date/variety | What minimum, modal and maximum were reported for 1st Sort onion in Daudnagar on 17 Oct 2026? | ₹4,000 / ₹4,100 / ₹4,200 per quintal. |
| Q10 | No data | Are there any stored Arwal potato observations on 1 Jan 1900? | No records in the database for that filter. Do not infer that no trading occurred. |

## Commands

From the project root:

```cmd
python eval/round2_demo.py
python -m unittest discover -s tests -p test_round2_demo.py -v
python eval/round2_demo.py --live --output phase3_live_demo.json
```

The first command needs only Python and the four JSONL files. It compares all
ten results with the checked-in expected rows and records input-file hashes
when using `--output`. The live command needs `pymongo`, access to your
local seeded database, and the existing `mandi_locations.location` 2dsphere
index for Q02. It uses `MONGODB_URI` and `MONGODB_DATABASE` if set; otherwise
it reads `mongodb://localhost:27017` and `bihar_agriculture`. It does not
create indexes, change data, fetch websites, or call a model. Use a read-only
database account if available. A baseline difference or connection/query error
returns a nonzero exit code. Re-run using a new output filename; the script
does not overwrite earlier evidence.

## What to show in the viva

1. Show Q02 with the verified coordinate and its precision; use the map if
   available. For Q03 show the date sequence and variety caveat. For Q07
   retain the original Hindi in the evidence.
2. For Q05, Q06 and Q08, open the actual workbook row, PDF page (and exact
   quote) and API/raw snapshot plus the corresponding extraction log. A
   passing query verifies the stored fields, not that these originals were
   independently checked. If an original is unavailable, mark that trace as
   not independently verified.
3. Run the prompts through the relevant app or agent during the actual demo
   and compare with the database evidence. Keep the database answer, natural
   language answer and raw source checks separate. The terminal harness is
   not a substitute for the viva's live app queries or unseen inputs.
4. If a refreshed row differs, keep the observed answer, explain the change
   and verify it from the new source or run. Do not update the baseline just
   to turn a failure green. Put the evaluated commit/tag and environment in
   the demo log; the current faculty slot must be confirmed separately.
