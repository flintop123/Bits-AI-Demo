# Daily Mandi API Agent

## Responsibility

The agent collects date-bounded price observations from the public Bihar Krishi mandi API. It follows pagination, rejects records outside the requested date, normalizes official identifiers, and performs duplicate-safe MongoDB upserts.

## Sources

- Bihar Krishi mandi page: `https://www.biharkrishi.in/mandi`
- Public `agriMarket` JSON endpoint documented in `docs/evidence/phase4_mandi_api_contract.json`

## Inputs and outputs

| Item | Contract |
|---|---|
| Input | One or more ISO dates (`YYYY-MM-DD`) |
| Decision | One deterministic tool invocation per date |
| Tool | `BiharMandiApiClient.fetch_day` |
| Output | Normalized mandi observations plus a run trace |
| Storage | `bihar_agriculture.mandi_prices` and `mandi_ingestion_runs` |

The output retains the official record ID, district/market/commodity codes, observation date, prices, units, source timestamps, run ID, extracting agent and source URL.

## Model and fixed-code boundary

No language model is used. Date validation, pagination, normalization, retry behaviour and duplicate handling are fixed Python code. This is intentional because the source contract is structured and deterministic.

## Tools

- Python standard-library HTTP client
- MongoDB/PyMongo
- Windows Task Scheduler for daily execution

## Error case

HTTP 429, server errors and timeouts are retried within a bounded limit. An incomplete pagination sequence or a record outside the requested date fails the run rather than silently accepting partial data.

## Limitations

- Availability depends on the public Bihar Krishi endpoint.
- The source can revise historical rows; duplicate-safe upserts preserve one current record per official record ID and day.
- Geographic coordinates are added only after separate conservative verification.
