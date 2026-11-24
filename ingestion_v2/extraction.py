"""Read-only extraction tools with record- and field-level locators."""

from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
from pathlib import Path

from openpyxl.utils import get_column_letter
from ingestion_v2.pdf_sections import leading_heading

from ingestion_v2.models import (
    ExtractedRecord,
    ExtractFileInput,
    ExtractFileOutput,
    ExtractionMetrics,
    InspectFileInput,
    InspectFileOutput,
    SourceLocator,
    SourceModality,
)


SUPPORTED_SUFFIXES = {
    ".pdf": SourceModality.PDF,
    ".xlsx": SourceModality.EXCEL,
    ".xls": SourceModality.EXCEL,
    ".csv": SourceModality.CSV,
    ".json": SourceModality.JSON,
}


def inspect_input_file(payload: InspectFileInput):
    path = Path(payload.file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")
    modality = SUPPORTED_SUFFIXES.get(path.suffix.lower())
    if modality is None:
        raise ValueError(f"Unsupported input type: {path.suffix or '<none>'}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return InspectFileOutput(
        file_path=str(path),
        source_file=path.name,
        source_hash=digest,
        size_bytes=path.stat().st_size,
        modality=modality,
        mime_type=mime_type,
        supported=True,
    )


def extract_supported_file(payload: ExtractFileInput):
    inspection = inspect_input_file(InspectFileInput(file_path=payload.file_path))
    dispatch = {
        SourceModality.PDF: _extract_pdf,
        SourceModality.EXCEL: _extract_excel,
        SourceModality.CSV: _extract_csv,
        SourceModality.JSON: _extract_json,
    }
    return dispatch[inspection.modality](inspection, payload)


def _metrics(attempted, extracted, records):
    skipped = max(attempted - extracted, 0)
    coverage = extracted / attempted if attempted else 0
    return ExtractionMetrics(
        source_units_attempted=attempted,
        source_units_extracted=extracted,
        records_extracted=records,
        units_skipped=skipped,
        extraction_coverage=coverage,
    )


def _extract_pdf(inspection, payload):
    from tools.pdf_extractor.agriculture_pdf_extractor import (
        AgriculturePDFExtractor,
    )

    extractor = AgriculturePDFExtractor(
        ocr_language="+".join(payload.languages),
    )
    source_url = Path(inspection.file_path).as_uri()
    raw_records = extractor.load(
        inspection.file_path,
        source_url=source_url,
        document_title=Path(inspection.source_file).stem,
        force_ocr=payload.force_ocr,
    )
    records = []
    for index, record in enumerate(raw_records):
        locator = SourceLocator(
            source_file=inspection.source_file,
            source_url=source_url,
            modality=SourceModality.PDF,
            page_number=record["page_number"],
            chunk_index=record["chunk_index"],
            section_heading=leading_heading(record["content"]),
        )
        records.append(ExtractedRecord(
            record_index=index,
            data=record,
            field_locators={key: locator for key in record},
            record_locator=locator,
        ))
    report = extractor.last_report
    attempted = report.get("pages_requested", 0)
    extracted = report.get("pages_extracted", 0)
    warnings = []
    if report.get("skipped_pages"):
        warnings.append(f"{report['skipped_pages']} PDF page(s) contained no usable text")
    return ExtractFileOutput(
        modality=SourceModality.PDF,
        extraction_method="pypdf_tesseract_extractor",
        records=records,
        metrics=_metrics(attempted, extracted, len(records)),
        warnings=warnings,
    )


def _json_value(value):
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except (ImportError, TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _extract_excel(inspection, _payload):
    import pandas as pd

    sheets = pd.read_excel(inspection.file_path, sheet_name=None, header=None)
    records = []
    attempted = 0
    extracted = 0
    for sheet_name, frame in sheets.items():
        attempted += len(frame.index)
        for row_index, row in frame.iterrows():
            if row.isna().all():
                continue
            extracted += 1
            data = {}
            locators = {}
            for column_index, value in enumerate(row.tolist(), start=1):
                source_field = get_column_letter(column_index)
                data[source_field] = _json_value(value)
                locators[source_field] = SourceLocator(
                    source_file=inspection.source_file,
                    source_url=Path(inspection.file_path).as_uri(),
                    modality=SourceModality.EXCEL,
                    sheet_name=str(sheet_name),
                    row_number=row_index + 1,
                    column_name=source_field,
                    cell_reference=f"{source_field}{row_index + 1}",
                )
            record_locator = SourceLocator(
                source_file=inspection.source_file,
                source_url=Path(inspection.file_path).as_uri(),
                modality=SourceModality.EXCEL,
                sheet_name=str(sheet_name),
                row_number=row_index + 1,
            )
            records.append(ExtractedRecord(
                record_index=len(records),
                data=data,
                field_locators=locators,
                record_locator=record_locator,
            ))
    return ExtractFileOutput(
        modality=SourceModality.EXCEL,
        extraction_method="pandas_cell_aware_extractor",
        records=records,
        metrics=_metrics(attempted, extracted, len(records)),
    )


def _extract_csv(inspection, _payload):
    records = []
    with Path(inspection.file_path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_index, row in enumerate(reader, start=2):
            locators = {
                key: SourceLocator(
                    source_file=inspection.source_file,
                    source_url=Path(inspection.file_path).as_uri(),
                    modality=SourceModality.CSV,
                    row_number=row_index,
                    column_name=key,
                )
                for key in row
            }
            record_locator = SourceLocator(
                source_file=inspection.source_file,
                source_url=Path(inspection.file_path).as_uri(),
                modality=SourceModality.CSV,
                row_number=row_index,
            )
            records.append(ExtractedRecord(
                record_index=len(records),
                data=dict(row),
                field_locators=locators,
                record_locator=record_locator,
            ))
    count = len(records)
    return ExtractFileOutput(
        modality=SourceModality.CSV,
        extraction_method="python_csv_locator_extractor",
        records=records,
        metrics=_metrics(count, count, count),
    )


def _records_from_json(payload):
    if isinstance(payload, list):
        return payload, "$"
    if isinstance(payload, dict):
        for key in ("Data", "records", "items", "results"):
            if isinstance(payload.get(key), list):
                return payload[key], f"$.{key}"
    raise ValueError("JSON input must be a list or contain a recognized record list")


def _extract_json(inspection, _payload):
    payload = json.loads(Path(inspection.file_path).read_text(encoding="utf-8-sig"))
    raw_records, root_path = _records_from_json(payload)
    records = []
    warnings = []
    for index, item in enumerate(raw_records):
        if not isinstance(item, dict):
            warnings.append(f"Record {index} is not an object and was skipped")
            continue
        base_path = f"{root_path}[{index}]"
        locators = {
            key: SourceLocator(
                source_file=inspection.source_file,
                source_url=Path(inspection.file_path).as_uri(),
                modality=SourceModality.JSON,
                json_path=f"{base_path}.{key}",
            )
            for key in item
        }
        record_locator = SourceLocator(
            source_file=inspection.source_file,
            source_url=Path(inspection.file_path).as_uri(),
            modality=SourceModality.JSON,
            json_path=base_path,
        )
        records.append(ExtractedRecord(
            record_index=index,
            data=item,
            field_locators=locators,
            record_locator=record_locator,
        ))
    return ExtractFileOutput(
        modality=SourceModality.JSON,
        extraction_method="jsonpath_record_extractor",
        records=records,
        metrics=_metrics(len(raw_records), len(records), len(records)),
        warnings=warnings,
    )
