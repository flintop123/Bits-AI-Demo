import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ingestion_v2.evidence_report import (
    collect_run_evidence,
    compare_run_evidence,
    write_run_evidence_report,
)


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def make_run(root, run_id, *, valid, write_mode="dry_run"):
    directory = root / run_id
    directory.mkdir()
    source = {
        "file_path": "C:/inputs/prices.json",
        "source_file": "prices.json",
        "source_hash": "a" * 64,
        "size_bytes": 100,
        "modality": "json",
        "mime_type": "application/json",
        "supported": True,
    }
    metrics = {
        "source_units_attempted": 1,
        "source_units_extracted": 1,
        "candidate_records": 1,
        "valid_records": int(valid),
        "rejected_records": int(not valid),
        "inserted": int(valid and write_mode == "write"),
        "matched": 0,
        "modified": 0,
        "extraction_coverage": 1.0,
        "required_field_coverage": 1.0,
        "validation_rate": float(valid),
        "persistence_rate": float(valid and write_mode == "write"),
    }
    run = {
        "run_id": run_id,
        "status": "completed" if valid else "partial",
        "source": source,
        "target_collection": "mandi_prices",
        "metrics": metrics,
        "write_mode": write_mode,
        "warnings": [],
        "failures": [],
    }
    locator = {
        "source_file": "prices.json",
        "source_url": "file:///C:/inputs/prices.json",
        "modality": "json",
        "json_path": "$[0]",
    }
    source_data = {
        "district": "अरवल", "market": "अरवल", "date": "2026-10-17",
        "crop": "आलू", "variety": "Local", "price": 1200,
        "minimum_price": 1100, "maximum_price": 1250, "unit": "quintal",
    }
    mapped_data = dict(source_data)
    mapped_data.update({
        "source_record_id": "record-1",
        "source_url": "file:///C:/inputs/prices.json",
        "extraction_run_id": run_id,
    })
    field_locator = dict(locator, json_path="$[0].date")
    provenance = {
        "date": {
            "locator": field_locator,
            "raw_field": "date",
            "raw_value": "2026-10-17",
            "transformation": "date",
            "mapping_method": "model_proposed_schema_mapping",
            "confidence": 0.95,
        }
    }
    write_json(directory / "run.json", run)
    write_json(directory / "extraction.json", {
        "modality": "json",
        "extraction_method": "json_parser",
        "records": [{
            "record_index": 0,
            "data": source_data,
            "field_locators": {},
            "record_locator": locator,
        }],
        "metrics": {
            "source_units_attempted": 1,
            "source_units_extracted": 1,
            "records_extracted": 1,
            "units_skipped": 0,
            "extraction_coverage": 1.0,
        },
        "warnings": [],
    })
    error = [] if valid else ["date\n  Field required [type=missing]"]
    write_json(directory / "mapping.json", {
        "plan": {"target_collection": "mandi_prices"},
        "records": [{
            "target_collection": "mandi_prices",
            "data": mapped_data,
            "field_provenance": provenance,
            "mapping_confidence": 0.95,
            "valid": valid,
            "validation_errors": error,
        }],
        "records_attempted": 1,
        "records_valid": int(valid),
        "records_rejected": int(not valid),
        "required_field_coverage": 1.0,
        "validation_rate": float(valid),
    })
    write_json(directory / "persistence.json", {
        "write_mode": write_mode,
        "target_collection": "mandi_prices" if valid else "ingestion_quarantine",
        "attempted": 1,
        "eligible": int(valid),
        "inserted": int(valid and write_mode == "write"),
        "matched": 0,
        "modified": 0,
        "rejected": int(not valid),
        "quarantined": 0,
        "document_ids": [],
    })
    (directory / "events.jsonl").write_text(
        json.dumps({
            "sequence": 1,
            "timestamp": "2026-11-15T00:00:00+00:00",
            "stage": "mapping_validation",
            "status": "completed" if valid else "partial",
            "tool_name": "propose_and_apply_mapping",
            "tool_version": "2.0.0",
            "message": "Mapped record",
            "metrics": {},
            "error_type": None,
        }) + "\n",
        encoding="utf-8",
    )
    return directory, mapped_data


class IngestionEvidenceReportTests(unittest.TestCase):
    def test_report_shows_source_mapping_and_verified_mongo_record(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, mapped = make_run(
                root, "successful-run", valid=True, write_mode="write"
            )
            result = write_run_evidence_report(
                directory,
                mongo_verification={
                    "status": "verified",
                    "collection": "mandi_prices",
                    "query": {"extraction_run_id": "successful-run"},
                    "matched_count": 1,
                    "records": [mapped],
                },
            )
            report = result["report"]
            html = result["html"].read_text(encoding="utf-8")
        self.assertEqual(report["summary"]["validation_success_percent"], 100.0)
        self.assertEqual(report["summary"]["mongo_readback_count"], 1)
        record = report["record_comparisons"][0]
        self.assertEqual(record["source_data"]["crop"], "आलू")
        self.assertEqual(record["mongo_record"]["source_record_id"], "record-1")
        self.assertEqual(record["disposition"], "verified_in_mongodb")
        self.assertIn("Source → canonical schema → MongoDB", html)

    def test_rejected_run_distinguishes_extraction_from_validation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, _mapped = make_run(root, "failed-run", valid=False)
            report = collect_run_evidence(directory)
        self.assertEqual(report["summary"]["extraction_success_percent"], 100.0)
        self.assertEqual(report["summary"]["validation_success_percent"], 0.0)
        self.assertEqual(
            report["record_comparisons"][0]["disposition"],
            "rejected_by_schema_validation",
        )
        self.assertIn("schema mapping or validation", report["summary"]["interpretation"])

    def test_before_after_comparison_quantifies_improvement(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, _ = make_run(root, "before", valid=False)
            after, _ = make_run(root, "after", valid=True, write_mode="write")
            result = compare_run_evidence(before, after, root / "comparison")
            comparison = result["comparison"]
            self.assertTrue(result["json"].exists())
            self.assertTrue(result["html"].exists())
        self.assertIn("0.0% to 100.0%", comparison["conclusion"])



class EvidenceJoinRegressionTests(unittest.TestCase):
    def test_wrapped_json_rows_join_by_path_not_position(self):
        with TemporaryDirectory() as temporary:
            root, _ = make_run(Path(temporary), "wrapped", valid=True)
            path = root / "extraction.json"
            extraction = json.loads(path.read_text(encoding="utf-8"))
            original = extraction["records"][0]
            original["record_locator"]["json_path"] = "$.records[4]"
            wrong = {
                **original,
                "record_locator": {**original["record_locator"], "json_path": "$.records[1]"},
                "data": {"date": "wrong row"},
            }
            extraction["records"] = [wrong, original]
            write_json(path, extraction)
            path = root / "mapping.json"
            mapping = json.loads(path.read_text(encoding="utf-8"))
            mapping["records"][0]["field_provenance"]["date"]["locator"]["json_path"] = "$.records[4].date"
            write_json(path, mapping)
            comparison = collect_run_evidence(root)["record_comparisons"][0]
            self.assertEqual(comparison["source_match_status"], "matched")
            self.assertEqual(comparison["source_data"]["date"], "2026-10-17")
            mapping["records"][0]["field_provenance"]["date"]["locator"]["json_path"] = "$.records[2].date"
            write_json(path, mapping)
            comparison = collect_run_evidence(root)["record_comparisons"][0]
            self.assertEqual(comparison["source_match_status"], "unmatched_source_location")
            self.assertIsNone(comparison["source_data"])

    def test_duplicate_source_locator_cannot_claim_a_match(self):
        with TemporaryDirectory() as temporary:
            root, _ = make_run(Path(temporary), "duplicate", valid=True)
            path = root / "extraction.json"
            extraction = json.loads(path.read_text(encoding="utf-8"))
            extraction["records"] *= 2
            write_json(path, extraction)
            comparison = collect_run_evidence(root)["record_comparisons"][0]
            self.assertEqual(comparison["source_match_status"], "ambiguous_source_location")
            self.assertIsNone(comparison["source_data"])

    def test_distinguishes_wrong_run_and_value_mismatch_from_verified(self):
        with TemporaryDirectory() as temporary:
            root, row = make_run(Path(temporary), "current", valid=True, write_mode="write")
            mongo = {
                "status": "verified", "collection": "mandi_prices",
                "query": {"extraction_run_id": "current"}, "matched_count": 2,
                "records": [
                    {**row, "extraction_run_id": "previous"},
                    {**row, "price": 9999},
                    {**row, "date": "2026-10-18"},
                ],
            }
            report = collect_run_evidence(root, mongo_verification=mongo)
            result = report["record_comparisons"][0]
            self.assertEqual(result["disposition"], "mongodb_values_differ")
            self.assertEqual(result["mongo_differing_fields"], ["price"])
            self.assertEqual(report["summary"]["mongo_matched_row_count"], 0)
            mongo["query"]["extraction_run_id"] = "previous"
            result = collect_run_evidence(root, mongo_verification=mongo)["record_comparisons"][0]
            self.assertIsNone(result["mongo_record"])

    def test_dry_run_cannot_claim_a_mongo_match(self):
        with TemporaryDirectory() as temporary:
            root, row = make_run(Path(temporary), "dry", valid=True)
            mongo = {
                "status": "verified", "collection": "mandi_prices",
                "query": {"extraction_run_id": "dry"}, "matched_count": 1,
                "records": [row],
            }
            result = collect_run_evidence(root, mongo_verification=mongo)["record_comparisons"][0]
            self.assertEqual(result["disposition"], "validated_dry_run_no_write")
            self.assertIsNone(result["mongo_record"])


if __name__ == "__main__":
    unittest.main()
