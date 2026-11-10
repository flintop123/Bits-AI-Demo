"""Single-file, no-database-write entry point for the Phase II demonstration."""

import argparse
import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _json_value(value):
    if isinstance(value, (datetime, Path)):
        return str(value)
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except (ImportError, TypeError, ValueError):
        pass
    return value


def _generic_excel(path):
    import pandas as pd
    sheets = pd.read_excel(path, sheet_name=None)
    records = []
    for sheet, frame in sheets.items():
        for row_number, row in enumerate(frame.to_dict("records"), start=2):
            records.append({
                "sheet": sheet,
                "source_row": row_number,
                **{str(key): _json_value(value) for key, value in row.items()},
                "source_file": path.name,
            })
    return "generic_pandas_excel_extractor", records, {"sheets": list(sheets)}


def process_input(input_path, *, force_ocr=False, document_title=None):
    path = Path(input_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        from tools.pdf_extractor.agriculture_pdf_extractor import (
            AgriculturePDFExtractor,
        )
        extractor = AgriculturePDFExtractor()
        records = extractor.load(
            path,
            source_url=path.as_uri(),
            document_title=document_title or path.stem,
            force_ocr=force_ocr,
        )
        return "pypdf_tesseract_extractor", records, extractor.last_report

    if suffix in {".xlsx", ".xls"}:
        from tools.excel_extractor.excel_extractory import (
            CropStatisticsExcelExtractor,
        )
        try:
            records = CropStatisticsExcelExtractor().load(path)
            return "pandas_crop_statistics_extractor", records, {
                "recognized_schema": "crop_statistics"
            }
        except ValueError:
            return _generic_excel(path)

    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return "python_csv_reader", list(csv.DictReader(handle)), {}

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        raw_records = (
            payload if isinstance(payload, list)
            else payload.get("Data", payload.get("records", []))
        )
        if not isinstance(raw_records, list):
            raise ValueError("JSON input must be a list or contain Data/records list")
        if raw_records and {"id", "arrivalDate"}.issubset(raw_records[0]):
            from phase4.mandi_orchestrator import normalize_api_record
            collected_at = datetime.now(timezone.utc)
            run_id = str(uuid.uuid4())
            records = [
                normalize_api_record(
                    item, run_id=run_id, collected_at=collected_at
                )
                for item in raw_records
            ]
            return "bihar_mandi_json_normalizer", records, {"run_id": run_id}
        return "generic_json_reader", raw_records, {}

    raise ValueError(f"Unsupported input type: {suffix or '<none>'}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the AgriAgent file pipeline")
    parser.add_argument("--input", required=True, help="PDF, Excel, CSV, or JSON file")
    parser.add_argument("--output", default="artifacts/phase2/submission_run.json")
    parser.add_argument("--force-ocr", action="store_true")
    parser.add_argument("--document-title")
    args = parser.parse_args(argv)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    events = [{
        "event": "input_received", "timestamp": started.isoformat(),
        "input": str(Path(args.input).resolve()),
    }]
    try:
        tool, records, report = process_input(
            args.input,
            force_ocr=args.force_ocr,
            document_title=args.document_title,
        )
        agent = {
            "pypdf_tesseract_extractor": "multilingual_pdf_agent",
            "pandas_crop_statistics_extractor": "crop_statistics_excel_agent",
            "generic_pandas_excel_extractor": "generic_tabular_agent",
            "python_csv_reader": "generic_tabular_agent",
            "bihar_mandi_json_normalizer": "daily_mandi_api_agent",
            "generic_json_reader": "generic_structured_agent",
        }[tool]
        events.extend([
            {
                "event": "agent_selected",
                "agent_id": agent,
                "decision": (
                    "deterministic extension and schema routing; "
                    "no filename-specific output rule"
                ),
            },
            {"event": "tool_invoked", "agent_id": agent, "tool_name": tool},
            {
                "event": "tool_result", "agent_id": agent,
                "tool_name": tool, "record_count": len(records),
            },
            {
                "event": "output_validated", "status": "completed",
                "database_write": False,
            },
        ])
        result = {
            "run_id": report.get("run_id", run_id),
            "status": "completed",
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "input": str(Path(args.input).resolve()),
            "routing": {
                "extension": Path(args.input).suffix.lower(),
                "agent_id": agent,
                "selected_tool": tool,
            },
            "events": events,
            "record_count": len(records),
            "report": report,
            "records": records,
            "database_write": False,
        }
        return_code = 0
    except Exception as exc:
        events.append({
            "event": "run_failed", "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        })
        result = {
            "run_id": run_id, "status": "failed",
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "input": str(Path(args.input).resolve()),
            "events": events, "database_write": False,
        }
        return_code = 1
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_json_value),
        encoding="utf-8",
    )
    if return_code:
        print(f"Status: failed\nError: {events[-1]['error']}\nTrace: {output.resolve()}")
    else:
        print(
            f"Status: completed\nAgent: {result['routing']['agent_id']}\n"
            f"Tool: {result['routing']['selected_tool']}\n"
            f"Records: {result['record_count']}\nTrace: {output.resolve()}"
        )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
