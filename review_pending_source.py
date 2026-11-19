"""Preflight a manually obtained export for one pending source without network or DB access."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from zipfile import BadZipFile, ZipFile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
# A permitted extension describes the local export, not a supported live endpoint.
FORMATS = {
    "bihar_state_data_lab": {".csv", ".xlsx", ".json"},
    "bihar_horticulture_dynamic": {".csv", ".xlsx", ".json"},
    "bihar_seed_reports": {".pdf"},
    "nasa_appeears_modis": {".tif", ".tiff", ".nc", ".nc4"},
}
MAX_BYTES = 50 * 1024 * 1024


def _inventory(source_id):
    with (ROOT / "docs/source_agent_map.csv").open(encoding="utf-8-sig", newline="") as handle:
        matches = [row for row in csv.DictReader(handle) if row["source_id"] == source_id]
    if len(matches) != 1 or matches[0]["status"] != "pending":
        raise ValueError("Expected one pending source in the inventory")
    return matches[0]


def _origin(url):
    if url is None:
        return None
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or any(char.isspace() for char in url)):
        raise ValueError("Use a public HTTPS citation URL without credentials, query or fragment")
    return url


def _signature(path, suffix):
    with path.open("rb") as handle:
        header = handle.read(8)
    if suffix in {".tif", ".tiff"} and header[:4] in {
        b"II\x2a\x00", b"MM\x00\x2a", b"II\x2b\x00", b"MM\x00\x2b",
    }:
        return "TIFF-family"
    if suffix in {".nc", ".nc4"} and header[:4] in {b"CDF\x01", b"CDF\x02", b"CDF\x05"}:
        return "NetCDF classic family"
    if suffix in {".nc", ".nc4"} and header == b"\x89HDF\r\n\x1a\n":
        return "HDF5 (NetCDF-4 structure not verified)"
    raise ValueError(f"File signature does not match supported {suffix} preliminary checks")


def _clean_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        header = next(reader, [])
        if header and header[0].lstrip().startswith("<"):
            raise ValueError("Input appears to be a portal HTML page, not an exported CSV")
        normalized = [name.strip().casefold() for name in header]
        if not normalized or not all(normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("CSV headers are missing, empty or duplicated")
        for row in reader:
            if row and len(row) != len(header):
                raise ValueError(f"CSV field count differs from header at line {reader.line_num}")


def _clean_json(path):
    def reject_duplicates(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("JSON includes a duplicated property")
            out[key] = value
        return out
    def reject_constant(value):
        raise ValueError(f"Invalid JSON numeric value: {value}")
    json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=reject_duplicates,
               parse_constant=reject_constant)


def _check_xlsx(path):
    with ZipFile(path) as workbook:
        items = workbook.infolist()
        if "[Content_Types].xml" not in workbook.namelist() or "xl/workbook.xml" not in workbook.namelist():
            raise ValueError("Input is not an XLSX workbook container")
        if len(items) > 1000 or sum(item.file_size for item in items) > 2 * MAX_BYTES:
            raise ValueError("XLSX expands past the preflight limit; use a smaller sample")


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def review(source_id, path, *, origin_url=None, expected_sha256=None, force_ocr=False, plan=None):
    if source_id not in FORMATS:
        raise ValueError("Unknown pending source ID")
    entry = _inventory(source_id)
    origin_url = _origin(origin_url)
    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if suffix not in FORMATS[source_id]:
        raise ValueError(f"Use a local {', '.join(sorted(FORMATS[source_id]))} export for this source")
    if not path.is_file():
        raise ValueError("Local sample file was not found")
    size = path.stat().st_size
    if not 0 < size <= MAX_BYTES:
        raise ValueError("Provide a nonempty review sample no larger than 50 MiB")
    digest = _digest(path)
    if expected_sha256 is not None:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
            raise ValueError("Expected SHA-256 must be exactly 64 hexadecimal characters")
        if digest != expected_sha256.lower():
            raise ValueError("SHA-256 did not match the supplied value")
    if force_ocr and suffix != ".pdf":
        raise ValueError("OCR override applies to PDF samples only")
    result = {
        "source_id": source_id,
        "source_portal_in_inventory": entry["source_location"],
        "declared_export_url_unverified": origin_url,
        "inventory_status": entry["status"],
        "source_file": path.name,
        "sha256": digest,
        "matched_expected_sha256": expected_sha256 is not None,
        "size_bytes": size,
        "live_fetch_performed": False,
        "database_write_performed": False,
    }
    if source_id == "nasa_appeears_modis":
        if plan is not None:
            raise ValueError("Raster mapping is not supported by this preflight")
        result.update(status="signature_only", container_signature=_signature(path, suffix),
                      next_step="Verify product metadata, CRS, geotransform, bands, QA masks and district zonal summaries independently.")
        return result

    if suffix == ".csv":
        _clean_csv(path)
    if suffix == ".json":
        _clean_json(path)
    if suffix == ".xlsx":
        _check_xlsx(path)
    from ingestion_v2.extraction import extract_supported_file, inspect_input_file
    from ingestion_v2.models import ExtractFileInput, InspectFileInput

    inspection = inspect_input_file(InspectFileInput(file_path=str(path)))
    extraction = extract_supported_file(ExtractFileInput(file_path=str(path), force_ocr=force_ocr))
    if inspection.source_hash != digest or _digest(path) != digest:
        raise ValueError("Sample contents changed during preflight")
    if not extraction.records or not any(
        any(value is not None and value != "" for value in item.data.values())
        for item in extraction.records
    ):
        raise ValueError("No usable records were extracted")
    locators = []
    for record in extraction.records[:3]:
        locator = record.record_locator.model_dump(exclude_none=True, mode="json")
        locator.pop("source_url", None)  # Never include user's absolute file URL.
        locators.append(locator)
    result.update(
        status="extraction_with_warnings" if extraction.warnings else "local_extraction_checked",
        extraction_method=extraction.extraction_method,
        extraction_metrics=extraction.metrics.model_dump(mode="json"),
        warnings=extraction.warnings,
        observed_source_fields=sorted({str(field) for row in extraction.records for field in row.data}),
        sample_record_locators=locators,
        next_step="Review the source schema and run the in-memory mapping dry run with a reviewed plan.",
    )
    if plan is not None:
        from ingestion_v2.mapping import apply_mapping_plan
        from ingestion_v2.models import MappingPlan, MappingRequest
        reviewed = MappingPlan.model_validate_json(Path(plan).read_text(encoding="utf-8"))
        mapping = apply_mapping_plan(MappingRequest(
            run_id=f"pending-{source_id}-{digest[:12]}",
            inspection=inspection,
            extraction=extraction,
        ), reviewed)
        result["mapping"] = {
            "target_collection": reviewed.target_collection.value,
            "records_attempted": mapping.records_attempted,
            "records_valid": mapping.records_valid,
            "records_rejected": mapping.records_rejected,
            "required_field_coverage": mapping.required_field_coverage,
            "validation_rate": mapping.validation_rate,
        }
        full = mapping.records_valid > 0 and not mapping.records_rejected
        result["status"] = "local_mapping_validated" if full and not extraction.warnings else "local_mapping_needs_review"
        result["next_step"] = "Check mapped values and source locations against the source independently; preflight does not approve persistence."
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=sorted(FORMATS))
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--origin-url", help="Optional public citation URL; the tool does not fetch it")
    parser.add_argument("--sha256", help="Optional expected SHA-256 from an independently reviewed sample")
    parser.add_argument("--force-ocr", action="store_true")
    parser.add_argument("--plan", type=Path, help="Optional reviewed MappingPlan JSON; no records will be persisted")
    args = parser.parse_args(argv)
    try:
        result = review(args.source, args.sample, origin_url=args.origin_url,
                        expected_sha256=args.sha256, force_ocr=args.force_ocr, plan=args.plan)
    except (OSError, ValueError, csv.Error, ImportError, BadZipFile) as exc:
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 2 if result["status"] in {"extraction_with_warnings", "local_mapping_needs_review"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
