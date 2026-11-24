"""Standalone, auditable source-to-Mongo evidence for ingestion-v2 runs."""

from __future__ import annotations

from collections import Counter, defaultdict
from html import escape
import json
import os
from pathlib import Path
import re
from typing import Any


REPORT_VERSION = "2.1.0"
ALLOWLISTED_COLLECTIONS = {
    "agriculture_documents",
    "crop_statistics",
    "mandi_prices",
    "mandi_locations",
}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _load_events(path: Path):
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _percent(numerator, denominator):
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _locator_key(locator):
    locator = locator or {}
    modality = locator.get("modality")
    source = locator.get("source_url") or locator.get("source_file")
    if not source:
        return None
    if modality == "json":
        # Prefer the exact record boundary, including named array wrappers.
        match = re.match(r"^(\$(?:\.[^.\[]+)?\[\d+\])(?:\.|$)",
                         locator.get("json_path") or "")
        location = (match.group(1),) if match else None
    elif modality in {"excel", "csv"}:
        row = locator.get("row_number")
        sheet = locator.get("sheet_name")
        location = (sheet, row) if row is not None and (sheet or modality == "csv") else None
    elif modality == "pdf":
        page, chunk = locator.get("page_number"), locator.get("chunk_index")
        location = (page, chunk) if page is not None and chunk is not None else None
    else:
        location = None
    return (source, modality, *location) if location else None


def _locator_label(locator):
    locator = locator or {}
    parts = [locator.get("source_file")]
    if locator.get("json_path"):
        parts.append(locator["json_path"])
    if locator.get("sheet_name"):
        parts.append(f"sheet {locator['sheet_name']}")
    if locator.get("row_number"):
        parts.append(f"row {locator['row_number']}")
    if locator.get("cell_reference"):
        parts.append(f"cell {locator['cell_reference']}")
    if locator.get("page_number"):
        parts.append(f"page {locator['page_number']}")
    if locator.get("chunk_index") is not None:
        parts.append(f"chunk {locator['chunk_index']}")
    if locator.get("text_start") is not None and locator.get("text_end") is not None:
        parts.append(f"characters {locator['text_start']}:{locator['text_end']}")
    if locator.get("bounding_box"):
        parts.append(f"box {locator['bounding_box']}")
    return " · ".join(str(item) for item in parts if item) or "unknown locator"


def _source_match(mapped, extracted_by_locator):
    locators = [
        item.get("locator")
        for field, item in mapped.get("field_provenance", {}).items()
        if item.get("locator")
        # A wide Excel year may come from a separate header row. Its exact
        # cell remains in field lineage, not in the data-row join.
        and not (field == "year" and item["locator"].get("modality") == "excel"
                 and item.get("transformation") in {
            "wide_period_header", "wide_period_plan_unanchored",
        })
    ]
    keys = {_locator_key(locator) for locator in locators}
    keys.discard(None)
    if len(keys) > 1:
        return None, None, "multiple_source_locations"
    if keys:
        key = next(iter(keys))
        candidates = extracted_by_locator.get(key, ())
        if len(candidates) == 1:
            return candidates[0], candidates[0]["record_locator"], "matched"
        if len(candidates) > 1:
            return None, None, "ambiguous_source_location"
    return None, locators[0] if len(locators) == 1 else None, "unmatched_source_location"


_IDENTITY_FIELDS = {
    "agriculture_documents": ("source_url", "page_number", "chunk_index"),
    "crop_statistics": ("crop", "season", "year"),
    "mandi_prices": ("source_record_id", "date"),
    "mandi_locations": ("market_code",),
}


def _mongo_identity(record, target):
    fields = _IDENTITY_FIELDS.get(target)
    if not fields:
        return None
    values = tuple(record.get(field) for field in fields)
    return values if all(type(value) in (str, int) and value != "" for value in values) else None


def read_mongo_verification(run, *, uri=None, sample_limit=500):
    """Read back only records tagged with this run from an allowlisted collection."""
    target = run.get("target_collection")
    run_id = run.get("run_id")
    if target not in ALLOWLISTED_COLLECTIONS or not run_id or run.get("write_mode") != "write":
        return {
            "status": "not_applicable",
            "collection": target,
            "query": {"extraction_run_id": run_id},
            "matched_count": 0,
            "records": [],
        }
    try:
        from pymongo import MongoClient

        if not isinstance(sample_limit, int) or sample_limit < 1:
            raise ValueError("sample_limit must be positive")
        query = {"extraction_run_id": run_id}
        with MongoClient(
            uri or os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/"),
            serverSelectionTimeoutMS=5000,
        ) as client:
            collection = client["bihar_agriculture"][target]
            matched = collection.count_documents(query)
            records = list(collection.find(query).sort("_id", 1).limit(sample_limit))
        return {
            "status": "verified",
            "collection": target,
            "query": query,
            "matched_count": matched,
            "sampled_count": len(records),
            "sample_limit": sample_limit,
            "records": _json_safe(records),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "collection": target,
            "query": {"extraction_run_id": run_id},
            "matched_count": 0,
            "records": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def collect_run_evidence(run_directory, *, mongo_verification=None, max_records=100):
    run_directory = Path(run_directory)
    run = _load_json(run_directory / "run.json", {})
    extraction = _load_json(run_directory / "extraction.json", {})
    mapping = _load_json(run_directory / "mapping.json", {})
    persistence = _load_json(run_directory / "persistence.json", {})
    events = _load_events(run_directory / "events.jsonl")
    extracted_records = extraction.get("records", [])
    mapped_records = mapping.get("records", [])

    extracted_by_locator = defaultdict(list)
    for item in extracted_records:
        key = _locator_key(item.get("record_locator"))
        if key is not None:
            extracted_by_locator[key].append(item)
    mongo_verification = mongo_verification or {
        "status": "not_requested",
        "collection": run.get("target_collection"),
        "query": {"extraction_run_id": run.get("run_id")},
        "matched_count": 0,
        "records": [],
    }
    target = run.get("target_collection")
    run_id = run.get("run_id")
    readback_available = (
        bool(run_id)
        and target in ALLOWLISTED_COLLECTIONS
        and mongo_verification.get("status") == "verified"
        and mongo_verification.get("collection") == target
        and mongo_verification.get("query") == {"extraction_run_id": run_id}
        and persistence.get("write_mode") == "write"
    )
    mongo_by_identity = defaultdict(list)
    if readback_available:
        for item in mongo_verification.get("records", []):
            if item.get("extraction_run_id") != run_id:
                continue
            identity = _mongo_identity(item, target)
            if identity is not None:
                mongo_by_identity[identity].append(item)

    comparisons = []
    error_counter = Counter()
    for mapped in mapped_records:
        for error in mapped.get("validation_errors", []):
            first_line = next(
                (line.strip() for line in str(error).splitlines() if line.strip()),
                "Unknown validation error",
            )
            error_counter[first_line] += 1

    for index, mapped in enumerate(mapped_records[:max_records]):
        extracted, locator, source_match_status = _source_match(mapped, extracted_by_locator)
        mapped_data = dict(mapped.get("data", {}))
        mapped_data.pop("field_provenance", None)
        mongo_candidates = mongo_by_identity.get(_mongo_identity(mapped_data, target), ())
        mongo_record = mongo_candidates[0] if len(mongo_candidates) == 1 else None
        if mongo_record is None:
            differences = []
        else:
            differences = sorted(
                key for key, value in mapped_data.items()
                if key not in mongo_record or mongo_record[key] != value
            )
        errors = mapped.get("validation_errors", [])
        if not mapped.get("valid"):
            disposition = "rejected_by_schema_validation"
        elif len(mongo_candidates) > 1:
            disposition = "ambiguous_mongodb_identity"
        elif mongo_record is not None:
            disposition = "mongodb_values_differ" if differences else "verified_in_mongodb"
        elif persistence.get("write_mode") == "dry_run":
            disposition = "validated_dry_run_no_write"
        elif mapped.get("mapping_confidence", 0) < 0.85:
            disposition = "quarantined_low_confidence"
        else:
            disposition = "write_eligible_not_read_back"

        lineage = []
        for target_field, provenance in sorted(
            mapped.get("field_provenance", {}).items()
        ):
            lineage.append({
                "target_field": target_field,
                "source_field": provenance.get("raw_field"),
                "source_value": provenance.get("raw_value"),
                "mapped_value": mapped_data.get(target_field),
                "transformation": provenance.get("transformation"),
                "mapping_method": provenance.get("mapping_method"),
                "confidence": provenance.get("confidence"),
                "locator": provenance.get("locator"),
                "locator_label": _locator_label(provenance.get("locator")),
                "mongo_value": mongo_record.get(target_field) if mongo_record else None,
            })
        comparisons.append({
            "record_number": index + 1,
            "source_locator": (extracted or {}).get("record_locator", locator),
            "source_locator_label": _locator_label(
                (extracted or {}).get("record_locator", locator)
            ),
            "source_data": (extracted or {}).get("data"),
            "source_match_status": source_match_status,
            "mapped_data": mapped_data,
            "mongo_record": mongo_record,
            "mongo_differing_fields": differences,
            "mapping_confidence": mapped.get("mapping_confidence"),
            "valid": bool(mapped.get("valid")),
            "validation_errors": errors,
            "disposition": disposition,
            "field_lineage": lineage,
        })

    metrics = run.get("metrics", {})
    attempted = metrics.get("source_units_attempted", 0)
    extracted_count = metrics.get("source_units_extracted", 0)
    candidate = metrics.get("candidate_records", 0)
    valid = metrics.get("valid_records", 0)
    persisted = metrics.get("inserted", 0) + metrics.get("matched", 0)
    if extracted_count and not valid:
        interpretation = (
            "Extraction recovered source records, but schema mapping or validation "
            "rejected every candidate. No record was silently treated as successful."
        )
    elif valid and persistence.get("write_mode") == "dry_run":
        interpretation = (
            "Records passed schema validation. Database persistence was intentionally "
            "skipped because this was a dry run."
        )
    elif valid and persisted:
        interpretation = (
            "Records passed schema validation and were submitted through the "
            "allowlisted MongoDB upsert connector."
        )
    else:
        interpretation = "The run did not produce persistable canonical records."

    return {
        "report_version": REPORT_VERSION,
        "run_directory": str(run_directory),
        "run": run,
        "summary": {
            "status": run.get("status"),
            "source_file": (run.get("source") or {}).get("source_file"),
            "source_hash": (run.get("source") or {}).get("source_hash"),
            "modality": (run.get("source") or {}).get("modality"),
            "target_collection": run.get("target_collection"),
            "write_mode": run.get("write_mode"),
            "source_units_attempted": attempted,
            "source_units_extracted": extracted_count,
            "candidate_records": candidate,
            "valid_records": valid,
            "rejected_records": metrics.get("rejected_records", 0),
            "persisted_records": persisted,
            "extraction_success_percent": _percent(extracted_count, attempted),
            "validation_success_percent": _percent(valid, candidate),
            "persistence_success_percent": _percent(persisted, valid),
            "mongo_readback_count": mongo_verification.get("matched_count", 0),
            "mongo_matched_row_count": sum(
                item["disposition"] == "verified_in_mongodb" for item in comparisons
            ),
            "interpretation": interpretation,
        },
        "mapping_plan": mapping.get("plan") or run.get("mapping_plan"),
        "extraction_metrics": extraction.get("metrics", {}),
        "mapping_metrics": {
            key: mapping.get(key)
            for key in (
                "records_attempted", "records_valid", "records_rejected",
                "required_field_coverage", "validation_rate",
            )
        },
        "persistence": persistence,
        "mongo_verification": mongo_verification,
        "error_summary": [
            {"error": error, "records": count}
            for error, count in error_counter.most_common()
        ],
        "events": events,
        "record_comparisons": comparisons,
        "records_in_report": len(comparisons),
        "records_omitted": max(0, len(mapped_records) - len(comparisons)),
    }


def _pre(value):
    return f"<pre>{escape(json.dumps(value, ensure_ascii=False, indent=2, default=str))}</pre>"


def _metric_card(label, value, note=""):
    return (
        f'<article class="metric"><span>{escape(label)}</span>'
        f'<strong>{escape(str(value))}</strong><small>{escape(note)}</small></article>'
    )


def render_run_html(report):
    summary = report["summary"]
    events = "".join(
        "<tr>"
        f"<td>{item.get('sequence', '')}</td>"
        f"<td>{escape(str(item.get('timestamp', '')))}</td>"
        f"<td>{escape(str(item.get('stage', '')))}</td>"
        f"<td><span class=\"badge {escape(str(item.get('status', '')))}\">{escape(str(item.get('status', '')))}</span></td>"
        f"<td>{escape(str(item.get('tool_name') or '—'))}</td>"
        f"<td>{escape(str(item.get('message', '')))}</td>"
        "</tr>"
        for item in report["events"]
    )
    errors = "".join(
        f"<li><strong>{item['records']} record(s)</strong><span>{escape(item['error'])}</span></li>"
        for item in report["error_summary"]
    ) or "<li><strong>No schema-validation errors</strong></li>"
    records = []
    for item in report["record_comparisons"]:
        lineage = "".join(
            "<tr>"
            f"<td>{escape(str(row['target_field']))}</td>"
            f"<td>{escape(str(row['source_field'] or 'static/derived'))}</td>"
            f"<td>{escape(str(row['source_value']))}</td>"
            f"<td>{escape(str(row['mapped_value']))}</td>"
            f"<td>{escape(str(row['mongo_value']))}</td>"
            f"<td>{escape(str(row['transformation']))}</td>"
            f"<td>{escape(str(row['locator_label']))}</td>"
            "</tr>"
            for row in item["field_lineage"]
        )
        validation = (
            '<span class="badge completed">VALID</span>'
            if item["valid"]
            else '<span class="badge failed">REJECTED</span>'
        )
        record_errors = "".join(
            f"<pre class=\"error\">{escape(str(error))}</pre>"
            for error in item["validation_errors"]
        )
        records.append(
            f'<article class="record" data-disposition="{escape(item["disposition"])}">'
            f'<header><div><span>RECORD {item["record_number"]}</span><h3>{escape(item["source_locator_label"])}</h3></div>'
            f'<div>{validation}<small>{escape(item["disposition"])}</small></div></header>'
            '<div class="comparison">'
            f'<section><h4>1 · Extracted source</h4><p>{escape(item["source_match_status"])}</p>{_pre(item["source_data"])}</section>'
            f'<section><h4>2 · Canonical mapping</h4>{_pre(item["mapped_data"])}</section>'
            f'<section><h4>3 · MongoDB read-back</h4>{_pre(item["mongo_record"] or "Not read back / not written")}<p>{escape(", ".join(item["mongo_differing_fields"]))}</p></section>'
            '</div><details><summary>Field-by-field lineage</summary>'
            '<div class="table-wrap"><table><thead><tr><th>Target</th><th>Source field</th><th>Raw value</th><th>Mapped value</th><th>MongoDB value</th><th>Transform</th><th>Exact locator</th></tr></thead>'
            f'<tbody>{lineage}</tbody></table></div></details>{record_errors}</article>'
        )
    cards = "".join([
        _metric_card("Extraction", f"{summary['extraction_success_percent']}%", f"{summary['source_units_extracted']}/{summary['source_units_attempted']} source units"),
        _metric_card("Schema validation", f"{summary['validation_success_percent']}%", f"{summary['valid_records']}/{summary['candidate_records']} candidates"),
        _metric_card("Persistence", "Not attempted" if summary["write_mode"] == "dry_run" else f"{summary['persistence_success_percent']}%", f"{summary['persisted_records']} inserted or matched"),
        _metric_card("Mongo read-back", summary["mongo_readback_count"], report["mongo_verification"].get("status", "not requested")),
        _metric_card("Mapped values matched", summary["mongo_matched_row_count"], "among the rows shown below"),
    ])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ingestion evidence · {escape(str(report['run'].get('run_id', 'unknown')))}</title>
<style>
:root{{--ink:#18352c;--muted:#60746d;--forest:#12372a;--paper:#fffdf8;--cream:#f4efe5;--line:#d7ddd5;--orange:#d97927;--red:#a43c31;--green:#2f7657}}
*{{box-sizing:border-box}} body{{margin:0;color:var(--ink);background:var(--cream);font:15px/1.5 Inter,Segoe UI,Arial,sans-serif}} main{{max-width:1500px;margin:auto;padding:42px 28px 80px}}
.hero{{padding:38px;color:white;background:linear-gradient(135deg,#12372a,#1d5942);border-radius:20px}} .hero p{{max-width:1000px;color:#dbe7df}} h1{{margin:.2rem 0;font-size:clamp(30px,5vw,58px)}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:22px 0}} .metric{{padding:22px;background:var(--paper);border:1px solid var(--line);border-radius:14px}} .metric span,.metric small{{display:block;color:var(--muted)}} .metric strong{{display:block;margin:7px 0;font-size:32px}}
.panel,.record{{margin-top:22px;padding:25px;background:var(--paper);border:1px solid var(--line);border-radius:16px}} .record header{{display:flex;justify-content:space-between;gap:20px;align-items:start}} .record header span{{color:var(--orange);font-weight:800}} .record h3{{margin:3px 0 16px}}
.comparison{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}} .comparison section{{min-width:0;padding:15px;background:#f7f7f2;border:1px solid var(--line)}} h4{{margin:0 0 9px}}
pre{{max-height:360px;overflow:auto;margin:0;padding:13px;white-space:pre-wrap;word-break:break-word;background:#eef2ed;border-radius:7px;font:12px/1.45 Consolas,monospace}} pre.error{{margin-top:12px;color:#7b2119;background:#fff0ed}}
.badge{{display:inline-block;padding:4px 8px;border-radius:99px;color:white;background:#68736d;font-size:11px;font-weight:800;text-transform:uppercase}} .badge.completed{{background:var(--green)}} .badge.partial{{background:#b4731f}} .badge.failed{{background:var(--red)}}
.record header small{{display:block;margin-top:6px;color:var(--muted)}} details{{margin-top:14px}} summary{{cursor:pointer;font-weight:800}} .table-wrap{{overflow:auto;margin-top:12px}} table{{width:100%;border-collapse:collapse}} th,td{{padding:9px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}} th{{color:var(--muted);font-size:11px;text-transform:uppercase}}
.errors{{padding:0;list-style:none}} .errors li{{display:grid;grid-template-columns:170px 1fr;gap:15px;padding:11px 0;border-bottom:1px solid var(--line)}} .errors span{{word-break:break-word}} code{{font-family:Consolas,monospace}}
@media(max-width:950px){{.metrics{{grid-template-columns:1fr 1fr}}.comparison{{grid-template-columns:1fr}}}} @media(max-width:560px){{main{{padding:20px 12px}}.metrics{{grid-template-columns:1fr}}}}
</style></head><body><main>
<section class="hero"><span>AGRIAGENT · INGESTION V2 · AUDIT EVIDENCE</span><h1>{escape(str(summary.get('source_file') or 'Unknown source'))}</h1>
<p>{escape(summary['interpretation'])}</p><p><strong>Run:</strong> <code>{escape(str(report['run'].get('run_id')))}</code> · <strong>Status:</strong> {escape(str(summary['status']))} · <strong>Target:</strong> {escape(str(summary['target_collection']))} · <strong>Mode:</strong> {escape(str(summary['write_mode']))}</p></section>
<section class="metrics">{cards}</section>
<section class="panel"><h2>Why records passed or failed</h2><ul class="errors">{errors}</ul></section>
<section class="panel"><h2>Processing timeline</h2><div class="table-wrap"><table><thead><tr><th>#</th><th>Time</th><th>Stage</th><th>Status</th><th>Tool</th><th>Message</th></tr></thead><tbody>{events}</tbody></table></div></section>
<section class="panel"><h2>Mapping plan</h2>{_pre(report['mapping_plan'])}</section>
<section><h2>Source → canonical schema → MongoDB</h2>{''.join(records)}</section>
<section class="panel"><h2>Mongo verification</h2>{_pre(report['mongo_verification'])}</section>
</main></body></html>"""


def write_run_evidence_report(
    run_directory,
    *,
    verify_mongo=False,
    mongo_uri=None,
    mongo_verification=None,
    max_records=100,
):
    run_directory = Path(run_directory)
    run = _load_json(run_directory / "run.json", {})
    verification = mongo_verification
    if verification is None and verify_mongo:
        verification = read_mongo_verification(run, uri=mongo_uri)
    report = collect_run_evidence(
        run_directory,
        mongo_verification=verification,
        max_records=max_records,
    )
    json_path = run_directory / "evidence_report.json"
    html_path = run_directory / "evidence_report.html"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(render_run_html(report), encoding="utf-8")
    return {"json": json_path, "html": html_path, "report": report}


def compare_run_evidence(first_directory, second_directory, output_directory):
    first = collect_run_evidence(first_directory)
    second = collect_run_evidence(second_directory)
    metrics = (
        "source_units_extracted", "candidate_records", "valid_records",
        "rejected_records", "persisted_records",
        "extraction_success_percent", "validation_success_percent",
        "persistence_success_percent",
    )
    rows = [
        {
            "metric": metric,
            "before": first["summary"].get(metric, 0),
            "after": second["summary"].get(metric, 0),
        }
        for metric in metrics
    ]
    comparison = {
        "report_version": REPORT_VERSION,
        "before": {
            "run_id": first["run"].get("run_id"),
            "summary": first["summary"],
            "errors": first["error_summary"],
        },
        "after": {
            "run_id": second["run"].get("run_id"),
            "summary": second["summary"],
            "errors": second["error_summary"],
        },
        "metric_comparison": rows,
        "conclusion": (
            f"Validation improved from {first['summary']['validation_success_percent']}% "
            f"to {second['summary']['validation_success_percent']}%; rejected records "
            f"changed from {first['summary']['rejected_records']} to "
            f"{second['summary']['rejected_records']}."
        ),
    }
    table_rows = "".join(
        f"<tr><td>{escape(row['metric'])}</td><td>{escape(str(row['before']))}</td><td>{escape(str(row['after']))}</td></tr>"
        for row in rows
    )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ingestion run comparison</title>
<style>body{{max-width:1100px;margin:45px auto;padding:0 24px;color:#18352c;background:#f4efe5;font:16px/1.5 Segoe UI,Arial}}header,section{{padding:28px;margin:18px 0;background:#fffdf8;border:1px solid #d7ddd5;border-radius:16px}}header{{color:white;background:#12372a}}table{{width:100%;border-collapse:collapse}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #d7ddd5}}th{{color:#60746d}}code{{word-break:break-all}}</style></head><body>
<header><span>AGRIAGENT · BEFORE / AFTER EVIDENCE</span><h1>Ingestion correction comparison</h1><p>{escape(comparison['conclusion'])}</p></header>
<section><h2>Runs</h2><p><strong>Before:</strong> <code>{escape(str(comparison['before']['run_id']))}</code></p><p><strong>After:</strong> <code>{escape(str(comparison['after']['run_id']))}</code></p></section>
<section><h2>Quantitative results</h2><table><thead><tr><th>Metric</th><th>Before</th><th>After</th></tr></thead><tbody>{table_rows}</tbody></table></section>
<section><h2>Before: failure evidence</h2>{_pre(comparison['before']['errors'])}</section>
<section><h2>After: remaining failures</h2>{_pre(comparison['after']['errors'])}</section>
</body></html>"""
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "comparison.json"
    html_path = output_directory / "comparison.html"
    json_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(html, encoding="utf-8")
    return {"json": json_path, "html": html_path, "comparison": comparison}
