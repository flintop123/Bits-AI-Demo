# Temporal and Spatial Dashboard V2

## Purpose

This workstream answers the Phase II Round-2 request for weekly and monthly
report handling, district-wise temporal views, and an OpenStreetMap-based
spatial display. It extends the independent ingestion-v2 and read-only query
layers. It does not modify `agent.py`, `run_extractor.py`, or the ReAct layer.

## Implemented flow

1. The schema-mapping agent classifies a source as `daily`, `weekly`,
   `monthly`, `annual`, `event`, or `unknown`.
2. An explicit reporting window can be included in the reviewed mapping plan.
3. Canonical daily and annual records receive safe date-derived temporal
   metadata when the model leaves the frequency unknown.
4. Every temporal classification is recorded in field provenance with its
   mapping method and confidence.
5. The read-only district-trend API aggregates observations at daily, weekly,
   or monthly calendar grain.
6. The evidence dashboard exposes separate frequency controls, a district
   trend explorer, and verified markets on OpenStreetMap tiles.

## Data fields

| Field | Meaning | Evidence |
|---|---|---|
| `reporting_frequency` | Source/report grain | Model proposal or canonical safeguard |
| `reporting_period_start` | Inclusive ISO start date | Reviewed plan or canonical date/year |
| `reporting_period_end` | Inclusive ISO end date | Reviewed plan or canonical date/year |
| `field_provenance.reporting_frequency` | Classification method and confidence | Stored with each mapped record |

The official source value is preserved. Temporal aggregation creates a view;
it does not overwrite the daily observation.

## API

`GET /api/v1/mandi-prices/district-trends`

Parameters:

| Parameter | Allowed values | Default |
|---|---|---|
| `district` | Live catalog value | all |
| `crop` | Live catalog value | all |
| `variety` | Live catalog value | all |
| `frequency` | `daily`, `weekly`, `monthly` | `daily` |
| `periods` | 1–60 | 12 |

Example:

```text
/api/v1/mandi-prices/district-trends?district=Arwal&crop=Potato&frequency=weekly&periods=8
```

The API parses stored ISO observation dates, applies calendar-aligned periods,
and returns observation count, average modal price, minimum/maximum price,
market count, and crop count. These are descriptive aggregates, not forecasts.

## Dashboard evidence

- `scripts/build_github_pages_snapshot.py` derives daily, weekly, and monthly
  committed reporting series.
- District trend evidence is rebuilt from `db/dump/mandi_prices.jsonl`.
- `docs/assets/dashboard.js` renders frequency views and the district explorer.
- Leaflet 1.9.4 renders verified coordinates over OpenStreetMap standard tiles.
- The map retains OpenStreetMap attribution and describes points as verified
  market-locality centroids, not navigation coordinates.

## Verification commands

```powershell
python scripts\build_github_pages_snapshot.py
python -m unittest tests.test_ingestion_v2 tests.test_data_api tests.test_github_pages_dashboard -v
python -m unittest discover -s tests
git diff --check
```

## Safety and interpretation

- Only verified coordinates already stored in `mandi_locations` are plotted.
- The nearby-market endpoint remains radius-bounded and read-only.
- Weekly and monthly views aggregate source records; they do not claim a new
  government reporting cadence.
- Missing or ambiguous temporal metadata remains `unknown` unless a canonical
  date/year or a reviewed mapping plan supports classification.
