# Phase 6: visual analytics and collection observability

## Purpose

Phase 6 turns the collected records into a management-friendly visual layer.
It presents two complementary views in the existing Flask application:

1. a decision view for market coverage, price activity and nearby mandis; and
2. an operations view for collection progress, data quality and pipeline runs.

Every displayed metric is calculated from MongoDB when the page loads. The
dashboard does not use hard-coded demonstration totals.

## Dashboard contents

| Area | Live evidence shown |
| --- | --- |
| Summary | Mandi observations, covered dates, markets, districts and crops |
| Geospatial | Verified versus unresolved locations and coordinate plot |
| Temporal | Daily record volume for the selected 14, 30, 60 or 90 data days |
| Distribution | Highest-volume crops and districts |
| Automation | Latest collection run, writes, records and recent success rate |
| Quality | Price completeness, provenance completeness and coordinate verification |
| Source breadth | Historical crop-statistics records and document-language counts |

The visual market plot uses the verified GeoJSON coordinates from
`mandi_locations`. It is deliberately described as a coordinate plot rather
than a surveyed market-gate or road map because the current points are
market-locality centroids.

## Read-only API

```text
GET /api/v1/dashboard?days=30
```

The endpoint accepts a 1–365 data-day window and returns a single consistent
snapshot with summary KPIs, daily series, distributions, geospatial points,
recent run history and quality measurements.

## Running the visual dashboard

```powershell
python data_api.py
```

Then open `http://127.0.0.1:5000/`. MongoDB must be running. Ollama is needed
only for natural-language answers; the analytics dashboard itself does not
depend on the language model.

## Design and safety boundaries

- All dashboard operations are read-only.
- User coordinates are used only for the active nearby-price request.
- Charts are rendered with local HTML, CSS, JavaScript and SVG; no analytics
  data is sent to an external visualization service.
- Missing run history or empty collections are rendered as unavailable rather
  than replaced with invented values.
- Geocoding confidence and unresolved markets remain visible as quality
  indicators instead of being hidden.

## Future extensions

- district boundary choropleths from an authoritative licensed boundary file;
- explainable best-market scoring using distance, price and freshness;
- price-change alerts for selected crops and localities;
- downloadable dashboard snapshots for periodic faculty review; and
- longer-term forecasting after sufficient consistent daily history exists.
