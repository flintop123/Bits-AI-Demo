# Crop Statistics Excel Agent

## Responsibility

The agent extracts crop, season and financial-year observations from the Department of Agriculture and Farmers Welfare workbook. It aligns the Area, Production and Yield column blocks and normalizes each populated crop-season-year tuple.

## Inputs and outputs

| Item | Contract |
|---|---|
| Input | `data/Crop wise Area Production & Yield.xlsx` |
| Decision | Validate the expected measure blocks and shared year columns |
| Tool | pandas/openpyxl workbook extraction |
| Output | One normalized record per crop, season and year |
| Storage | `bihar_agriculture.crop_statistics` |

Each output includes values and units, advance-estimate status, source filename, source row, run ID and extracting agent.

## Model and fixed-code boundary

No language model is used. Header recognition, numeric conversion, unit assignment, advance-estimate marking and duplicate identity are deterministic Python rules.

## Tools

- pandas
- openpyxl
- MongoDB/PyMongo

## Error case

The agent stops with a named validation error when Area, Production or Yield blocks are absent, when their year columns do not intersect, or when no crop records can be extracted.

## Limitations

- The optimized parser expects the documented DA&FW workbook layout.
- Cotton and fibre crops use crop-specific production units; these units must not be converted to tonnes without an explicit rule.
- The generic submission entry point can preserve rows from an unfamiliar workbook, but it does not claim the same semantic normalization for an unknown layout.
