# District trends, reporting and market map

The read-only district-trend API and static dashboard are integrated from
`anuj/temporal-spatial-dashboard-v2` into the ingestion observability review
base. This integration does not alter the ingestion write path, the ReAct
pipeline, or the verified-source coordinates.

## Live district trends

`GET /api/v1/mandi-prices/district-trends` accepts the optional catalog filters
`district`, `crop`, `variety`, and `unit`. Set `frequency` to `daily`, `weekly`,
or `monthly`, and `periods` to 1–60 (default 12). For example:

```text
/api/v1/mandi-prices/district-trends?district=Arwal&crop=Potato&frequency=weekly&periods=8
```

Requires a MongoDB server supporting `$dateTrunc` (5.0 or later). Each row is
a calendar-aligned district/crop/unit group (Monday-start weeks) with price
observations, distinct observed dates, a date range, and market count. Distinct
crops and price units are never averaged together. The latest matched observation
anchors the window. Missing periods are omitted, not counted as zero; observed
periods can be incomplete. Prices are descriptive, not forecasts.

## Static dashboard and CSV exports

Run these from the repository root. Use unused filenames for the CSVs:

```text
python scripts/build_github_pages_snapshot.py
python scripts/export_mandi_period_report.py --frequency weekly --output mandi_weekly.csv
python scripts/export_mandi_period_report.py --frequency monthly --output mandi_monthly.csv
python -m http.server 8000 --directory docs
```

Open `http://127.0.0.1:8000/`. The HTML displays committed observations,
not a current fetch. The ingestion volume series comes from committed run
evidence. The district price chart and CSV use a single crop and unit (potato
per quintal if available) and up to six districts with the most observations
in that series from `db/dump/mandi_prices.jsonl`. Both CSVs include their evidence
cutoff, source, observation counts, and price unit. Excel can open their
UTF-8 Hindi labels. Reports should be regenerated from an updated, verified
snapshot when data changes.

### Optional Windows scheduling

First run `powershell -NoProfile -File .\scripts\run_period_report.ps1 -Frequency weekly`
from the repo to check that an export appears in `artifacts/period_reports/`.
On a nonstandard environment, append `-PythonExe "D:\path\to\python.exe"`.

In Windows Task Scheduler, add one weekly trigger (e.g. Monday at 09:00) and
one monthly trigger (e.g. the first day at 09:00) as separate tasks. For each
task, use `powershell.exe` as the Program and the following Arguments (change
`weekly` to `monthly` for the monthly task):

```text
-NoProfile -File "D:\path\to\Bits-AI-Demo\scripts\run_period_report.ps1" -Frequency weekly
```

Set **Start in** to your checkout path and run each task once from Task Scheduler
to check the exit code and the UTC-stamped CSV. This schedules exports only:
it depends on an up-to-date verified snapshot and does not start ingestion,
fetch new sources, or register any task for you.

The OpenStreetMap view shows already-verified market-locality centroids, not
navigation coordinates. The map needs network access for its Leaflet and tile
assets; the district series and reports do not. Source-reported temporal
metadata is separate from a grouped trend and is not changed by these reports.

## Verify

```text
python -m unittest discover -s tests -p "test_temporal_spatial_snapshot.py" -v
python -m unittest discover -s tests -p "test_github_pages_dashboard.py" -v
python -m unittest discover -s tests -p "test_district_trend_service.py" -v
python -m unittest discover -s tests -p "test_data_api.py" -v
```
