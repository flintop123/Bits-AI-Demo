# PDF table extraction (read-only)

The narrative semantic PDF agent remains unchanged. This tool handles tables in
text-layer PDFs: it reads a numeric cell only after matching its unique row label,
column header, explicit unit, and reviewed report context. It does not call an
LLM, route records into collections, or open a MongoDB connection.

## Run a reviewed profile

From the repository root in Windows CMD:

```bat
python -m ingestion_v2.pdf_tables --input "path\to\report.pdf" --profile "docs\ingestion_profiles\bihar_des_final_2024_25_crop_page3.json" --output "page3-evidence.json"
```

Use the category-page-4 profile for the same PDF's category totals. Both
profiles work only with the exact reviewed PDF bytes. They contain geometry
and text selectors, not hardcoded numeric results. Output is JSON; omit
`--output` to print it to stdout. With `--output`, the path must not already
exist. There is no write-to-database option.

## Add a different report

1. Obtain the PDF from a trusted source, inspect the actual rendered page,
   and pin its SHA-256 in `expected_sha256`. The extractor verifies equality
   to that fingerprint; a match does not by itself authenticate the publisher.
2. Set the physical (1-based) PDF page, exact row labels to extract, and a
   source-backed report heading on that page above the table. Add precise,
   unique anchors for period, estimate stage, jurisdiction, or other relevant
   context. These can refer to other physical pages in the same file.
3. Use `lines` / `lines_strict` for detectable ruled grids or `text` if
   supported by the layout. Use `positioned` for reviewed boundaries, such as
   a merged header: supply the table `clip` and strictly increasing column
   `x_edges`; the first and last edges must equal the clip's x limits. All
   coordinates are unrotated PDF points, with the origin at the upper left.
4. Set the number of header rows, the row-label column header, and the full
   text of each requested numeric column header. Units must occur explicitly
   in that column's header, or in a named preceding legend on the same page
   (`unit_context`). Compare a few cells, including at least one per column,
   with the original rendered PDF before relying on the output.

The tool aborts on a hash mismatch, ambiguous or missing table, duplicate or
missing requested rows, mismatched source text, absent units, or nonnumeric
target cells. It does not infer missing values, rescale reported quantities,
or read scanned-only tables with OCR. The selected values are decimal
strings with grouping commas removed; the source cell text is retained
separately. The evidence JSON contains source filename, fingerprint, page and
bounding boxes for the value, row label, header, unit, and context.

`extract_pdf_table` is also exposed through the ingestion-v2 tool schemas.
Existing ingestion, semantic quote checks, and ReAct behavior are unchanged.

Run focused regression tests:

```bat
python -m unittest tests.test_pdf_tables tests.test_ingestion_v2 tests.test_semantic_document_facts -v
```
