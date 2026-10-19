# Phase II database dictionary

The application uses MongoDB database `bihar_agriculture`. `schema.sql` is the required portable relational mirror used to explain and validate the same logical model; it does not imply that the runtime was migrated to SQL.

| Collection | Grain / identity | Purpose | Important provenance |
|---|---|---|---|
| `mandi_prices` | one official record (`source_record_id`) per market, crop, variety and day | daily modal/min/max price and arrival observations | `source_url`, `source_api`, `extraction_run_id`, `extracting_agent`, `extracted_at` |
| `crop_statistics` | crop + season + year | area, production and yield time series | source workbook and row, extraction run and agent |
| `agriculture_documents` | SHA-256 content hash per page chunk | searchable English/Hindi policy evidence | document, URL, page, chunk, language and extraction method |
| `mandi_locations` | official market code | verified GeoJSON point for nearby-market queries | precision, verification status and geocoding source |

Prices use rupees per quintal where the source supplies that unit. Locations use GeoJSON longitude-first order. Dates are stored as ISO `YYYY-MM-DD`; timestamps are UTC ISO strings. Unresolved locations are deliberately not written.

`db/dump/*.jsonl` is produced from the live local database just before submission. The committed dump is a reproducible evaluation snapshot, not an alternative source of truth.
