# Preflight for pending sources

Four source routes now have a local preflight. Keep their inventory status **pending**:
we have not confirmed a live endpoint, validated an authentic export for each route
or written any records. Existing configured agents remain unchanged.

From the repository root, with the existing dependencies installed:

| Source ID | Provide a manually acquired sample | Check performed |
| --- | --- | --- |
| `bihar_state_data_lab` | One public CSV, XLSX or supported-format JSON export | Extraction, shape, row/sheet/JSON locators and optional reviewed mapping |
| `bihar_horticulture_dynamic` | One public export from the specific dataset, not the landing page or existing BAIPP brochure | Same structured checks; do not equate an export test to a dynamic endpoint test |
| `bihar_seed_reports` | One official report PDF | Usable text/coverage and page/chunk anchors; optional `--force-ocr` for scans |
| `nasa_appeears_modis` | One small GeoTIFF or NetCDF AppEEARS export | Container signature only. HDF5 magic bytes do not establish NetCDF structure; TIFF magic bytes do not establish georeferencing. |

For example, replacing sample paths and IDs as appropriate:

```console
python review_pending_source.py --source bihar_state_data_lab --sample "samples/state_lab.csv"
python review_pending_source.py --source bihar_horticulture_dynamic --sample "samples/horticulture.xlsx"
python review_pending_source.py --source bihar_seed_reports --sample "samples/seed_report.pdf" --force-ocr
python review_pending_source.py --source nasa_appeears_modis --sample "samples/modis_land_cover.tif"
```

The only output is a JSON report on stdout, including SHA-256, a small set of
record locators, observed field names, and extraction/mapping counts where
applicable. No Mongo client or LLM is used, and the command cannot fetch files or
persist records. A public citation can be recorded with `--origin-url`; it is
not fetched or verified. To compare against an independently reviewed sample,
pass `--sha256`. A calculated digest alone does not prove source authenticity.

An optional `--plan reviewed.json` uses the existing ingestion-v2 mapping contract
in memory. Only use it when the source fits a supported canonical schema; do
not coerce seed or horticulture data into an unrelated collection. The mapping
rate measures validation, not value accuracy. Review source values, the reviewed
mapping contract and source locators before any pilot write. The generic reader
accepts structured JSON with a root list or one existing list key (`Data`,
`records`, `items` or `results`); a different export shape needs a deliberate reader
or explicit local conversion with preserved provenance. Only review files you
are authorized to use; do not commit the raw exports or signed download URLs.

Exit code 0 means the specific check completed, 1 means failure, and 2 flags
warnings or a mapping needing review. PDF OCR requires the existing Tesseract
dependencies including Hindi where applicable. The 50 MiB preflight input
limit is intended for sample exports, not entire archives.

Before enabling each route, verify the authentic sample and source schema,
document the official access contract and test the intended authorization and
refresh behavior. For AppEEARS/MODIS, also record product/version, granule dates,
QA masks, CRS, extent/transform, value legend and district boundary version,
then independently validate district zonal summaries. No raster spatial result
is demonstrated by this change.

```console
python -m unittest discover -s tests -p test_pending_source_review.py -v
```
