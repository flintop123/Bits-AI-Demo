"""Score reviewed source fields against an ingestion run, without writing to MongoDB."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
from html import escape
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ingestion_v2.evidence_report import (
    _IDENTITY_FIELDS, _mongo_identity, read_mongo_verification,
)
from ingestion_v2.models import StrictModel


Scalar = str | bool | int | float | None
_MISSING = object()
_OUTCOMES = ("correct", "wrong", "missing", "ambiguous", "not_checked")


class ExpectedField(StrictModel):
    value: Scalar
    source_location: str = Field(min_length=1, max_length=300)
    expected_locator: dict[str, str | int] = Field(default_factory=dict)


class ExpectedRecord(StrictModel):
    identity: dict[str, str | int]
    fields: dict[str, ExpectedField] = Field(min_length=1, max_length=100)


class FieldAccuracyManifest(StrictModel):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_collection: Literal[
        "mandi_prices", "crop_statistics", "mandi_locations", "agriculture_documents"
    ]
    records: list[ExpectedRecord] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def identity_contract(self):
        expected = set(_IDENTITY_FIELDS[self.target_collection])
        seen = set()
        for record in self.records:
            identity = _mongo_identity(record.identity, self.target_collection)
            if set(record.identity) != expected or identity is None:
                raise ValueError(f"identity must contain exactly {', '.join(sorted(expected))}")
            if identity in seen:
                raise ValueError("manifest contains duplicate record identity")
            seen.add(identity)
        return self


def _equal(actual, expected):
    if type(actual) in (float, int) and type(expected) in (float, int):
        return Decimal(str(actual)) == Decimal(str(expected))
    # In Python bool is a subclass of int, but never a valid numeric match here.
    return type(actual) is type(expected) and actual == expected


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _score(candidates, field, expected, *, available=True, exhaustive=True):
    if not available or (not candidates and not exhaustive):
        return {"status": "not_checked"}
    if len(candidates) > 1:
        return {"status": "ambiguous", "matching_records": len(candidates)}
    actual = candidates[0].get(field, _MISSING) if candidates else _MISSING
    if actual is _MISSING or (expected is not None and actual in (None, "")):
        return {"status": "missing"}
    return {"status": "correct" if _equal(actual, expected) else "wrong", "actual": actual}


def _index(records, target):
    index = defaultdict(list)
    for row in records:
        identity = _mongo_identity(row, target)
        if identity is not None:
            index[identity].append(row)
    return index


def _summary(results, key):
    counts = Counter(row[key]["status"] for row in results)
    total = len(results)
    checked = total - counts["not_checked"]
    return {
        "expected_fields": total,
        "checked_fields": checked,
        **{outcome: counts[outcome] for outcome in _OUTCOMES},
        "correct_pct_of_expected": round(100 * counts["correct"] / total, 2),
        "correct_pct_of_checked": round(100 * counts["correct"] / checked, 2) if checked else None,
    }


def audit_fields(run_directory, source_path, manifest, *, verify_mongo=False):
    run_directory = Path(run_directory)
    run = _read(run_directory / "run.json")
    run_id = run.get("run_id")
    target = manifest.target_collection
    if not run_id or run.get("target_collection") != target:
        raise ValueError("manifest target does not identify the requested ingestion run")
    source_sha256 = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    if not source_sha256 == manifest.source_sha256 == (run.get("source") or {}).get("source_hash"):
        raise ValueError("source PDF/Excel/JSON bytes, run and reviewed manifest hashes must match")

    mapping = _read(run_directory / "mapping.json")
    mapped_records = []
    for candidate in mapping["records"]:
        if candidate.get("target_collection") != target:
            continue
        record = candidate.get("data")
        if not isinstance(record, dict) or (
            record.get("extraction_run_id") != run_id
            or record.get("source_hash") != source_sha256
        ):
            raise ValueError("mapping artifact is not tied to the same run and source")
        mapped_records.append(record)
    mapped = _index(mapped_records, target)

    receipt = read_mongo_verification(run) if verify_mongo else {"status": "not_requested"}
    query_ok = receipt.get("query") == {"extraction_run_id": run_id}
    mongo_available = (
        run.get("write_mode") == "write" and receipt.get("status") == "verified"
        and receipt.get("collection") == target and query_ok
    )
    verified = [
        record for record in receipt.get("records", [])
        if record.get("extraction_run_id") == run_id
        and record.get("source_hash") == source_sha256
    ] if mongo_available else []
    # If filtering removed any records or the read-back was truncated, an absent
    # identity is not proof that a MongoDB record is missing.
    exhaustive = mongo_available and receipt.get("matched_count") == len(verified)
    stored = _index(verified, target)
    results = []
    for record in manifest.records:
        identity = _mongo_identity(record.identity, target)
        mapped_candidates = mapped[identity]
        mongo_candidates = stored[identity]
        for field, expected in record.fields.items():
            locator = None
            if len(mapped_candidates) == 1:
                provenance = mapped_candidates[0].get("field_provenance") or {}
                locator = (provenance.get(field) or {}).get("locator")
            provenance_match = None
            if expected.expected_locator:
                provenance_match = isinstance(locator, dict) and all(
                    locator.get(key) == expected_value
                    for key, expected_value in expected.expected_locator.items()
                )
            results.append({
                "identity": record.identity,
                "field": field,
                "reviewed_source_location": expected.source_location,
                "expected": expected.value,
                "actual_locator": locator,
                "provenance_match": provenance_match,
                "mapped": _score(mapped_candidates, field, expected.value),
                "mongo": _score(
                    mongo_candidates, field, expected.value,
                    available=mongo_available, exhaustive=exhaustive,
                ),
            })
    return {
        "run_id": run_id,
        "target_collection": target,
        "source_sha256": source_sha256,
        "reference": "human-reviewed expected values and source locators",
        "mongo_readback": receipt.get("status", "unavailable"),
        "mongo_exhaustive": exhaustive,
        "mapped_accuracy": _summary(results, "mapped"),
        "mongo_accuracy": _summary(results, "mongo"),
        "fields": results,
    }


def render_audit_html(report, events):
    def cell(value):
        return escape(json.dumps(value, ensure_ascii=False)) if value is not None else "—"

    totals = []
    for label, data in (("Mapped fields", report["mapped_accuracy"]), ("MongoDB read-back", report["mongo_accuracy"])):
        totals.append(
            f"<li>{label}: {data['correct']}/{data['expected_fields']} correct; "
            f"{data['wrong']} wrong, {data['missing']} missing, "
            f"{data['ambiguous']} ambiguous, {data['not_checked']} not checked</li>"
        )
    rows = []
    for row in report["fields"]:
        source = escape(row["reviewed_source_location"])
        rows.append(
            f"<tr><td>{cell(row['identity'])}<br>{escape(row['field'])}</td>"
            f"<td>{source}<br><strong>{cell(row['expected'])}</strong><br>{cell(row['actual_locator'])}</td>"
            f"<td>{escape(row['mapped']['status'])}: {cell(row['mapped'].get('actual'))}</td>"
            f"<td>{escape(row['mongo']['status'])}: {cell(row['mongo'].get('actual'))}</td></tr>"
        )
    timeline = []
    for event in events:
        stage = escape(str(event.get("stage", "")))
        status = escape(str(event.get("status", "")))
        message = escape(str(event.get("message", "")))
        timestamp = escape(str(event.get("timestamp", "")))
        timeline.append(f"<li><strong>{stage} · {status}</strong><br>{timestamp}<br>{message}</li>")
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        "<title>Round 2 | Source-to-field accuracy</title>"
        "<style>body{font:16px system-ui;margin:clamp(1rem,4vw,3rem);color:#18372d}"
        ".view{display:grid;grid-template-columns:minmax(0,3fr) minmax(15rem,1fr);gap:1.5rem}"
        "table{width:100%;border-collapse:collapse;text-align:left}"
        "th,td{border-bottom:1px solid #cbd3c8;padding:.6rem;vertical-align:top;overflow-wrap:anywhere}"
        "ol{padding-left:1.5rem}li{margin:.5em 0}.table{overflow:auto}"
        "@media(max-width:850px){.view{grid-template-columns:minmax(0,1fr)}}</style>"
        "<h1>Source-to-field accuracy</h1>"
        f"<p>Run {escape(str(report['run_id']))} · {escape(report['target_collection'])} · "
        f"SHA-256 {escape(report['source_sha256'])}</p><ul>{''.join(totals)}</ul>"
        "<p>Expected fields were manually reviewed. No MongoDB writes were performed by this audit.</p>"
        "<div class=view><section class=table><h2>Field comparison</h2><table><thead><tr>"
        "<th>Record / field</th><th>Reviewed source / extracted locator</th>"
        f"<th>Mapped value</th><th>Stored value</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"</section><aside><h2>Processing log</h2><ol>{''.join(timeline)}</ol></aside></div></html>"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--verify-mongo", action="store_true", help="Read records from the saved run only")
    parser.add_argument("--html", type=Path, help="Create a new standalone side-by-side audit report")
    args = parser.parse_args(argv)
    try:
        report = audit_fields(
            args.run_dir, args.source, FieldAccuracyManifest.model_validate(_read(args.manifest)),
            verify_mongo=args.verify_mongo,
        )
        if args.html:
            event_path = Path(args.run_dir) / "events.jsonl"
            events = [
                json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ] if event_path.is_file() else []
            html = render_audit_html(report, events)
            with args.html.open("x", encoding="utf-8") as stream:
                stream.write(html)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Field accuracy audit failed: {exc}\n")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
