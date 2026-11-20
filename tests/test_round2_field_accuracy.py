from contextlib import redirect_stderr
import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ingestion_v2.field_accuracy import FieldAccuracyManifest, audit_fields, render_audit_html
from ingestion_v2.models import IngestionRun, RunStatus, WriteMode
from ingestion_v2.run_store import LocalIngestionRunStore
from run_ingestion_v2 import _progress_line, parse_args


class FieldAccuracyTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.source = self.directory / "fixture.json"
        self.source.write_text('{"price":1200,"market":"Arwal","unit":"quintal"}', encoding="utf-8")
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.identity = {"source_record_id": "fixture-record", "date": "2025-10-05"}
        self.target = "mandi_prices"
        self.manifest = FieldAccuracyManifest.model_validate({
            "source_sha256": self.digest,
            "target_collection": self.target,
            "records": [{
                "identity": self.identity,
                "fields": {
                    "price": {
                        "value": 1200, "source_location": "$.price",
                        "expected_locator": {"json_path": "$.price"},
                    },
                    "market": {"value": "Arwal", "source_location": "$.market"},
                    "unit": {"value": "quintal", "source_location": "$.unit"},
                },
            }],
        })
        self.record = {
            **self.identity, "extraction_run_id": "run-a", "source_hash": self.digest,
            "price": 1200.0, "market": "Patna",
            "field_provenance": {"price": {"locator": {"json_path": "$.price"}}},
        }
        self.save("run.json", {
            "run_id": "run-a", "target_collection": self.target, "write_mode": "write",
            "source": {"source_hash": self.digest},
        })
        self.save("mapping.json", {"records": [{"target_collection": self.target, "data": self.record}]})

    def save(self, name, data):
        (self.directory / name).write_text(json.dumps(data), encoding="utf-8")

    def test_correct_wrong_missing_and_unrequested_mongo_are_separate(self):
        with patch("ingestion_v2.field_accuracy.read_mongo_verification") as readback:
            report = audit_fields(self.directory, self.source, self.manifest)
        readback.assert_not_called()
        counts = report["mapped_accuracy"]
        self.assertEqual([counts[key] for key in ("correct", "wrong", "missing")], [1, 1, 1])
        self.assertEqual(counts["correct_pct_of_expected"], 33.33)
        self.assertEqual(report["mongo_accuracy"]["not_checked"], 3)
        self.assertIsNone(report["mongo_accuracy"]["correct_pct_of_checked"])
        self.assertTrue(report["fields"][0]["provenance_match"])

    def test_verified_mongo_compares_to_reference_not_mapping(self):
        self.assertEqual(self.record["market"], "Patna")
        receipt = {
            "status": "verified", "collection": self.target, "query": {"extraction_run_id": "run-a"},
            "matched_count": 1,
            "records": [{**self.record, "market": "Arwal", "unit": "quintal"}],
        }
        with patch("ingestion_v2.field_accuracy.read_mongo_verification", return_value=receipt):
            report = audit_fields(self.directory, self.source, self.manifest, verify_mongo=True)
        self.assertEqual(report["mongo_accuracy"]["correct"], 3)
        self.assertEqual(report["mapped_accuracy"]["correct"], 1)

    def test_truncated_readback_does_not_claim_missing(self):
        with patch("ingestion_v2.field_accuracy.read_mongo_verification", return_value={
            "status": "verified", "collection": self.target, "query": {"extraction_run_id": "run-a"},
            "matched_count": 7, "records": [],
        }):
            report = audit_fields(self.directory, self.source, self.manifest, verify_mongo=True)
        self.assertEqual(report["mongo_accuracy"]["not_checked"], 3)
        self.assertEqual(report["mongo_accuracy"]["missing"], 0)

    def test_rejects_modified_source_before_mongo(self):
        self.source.write_text("not the audited input", encoding="utf-8")
        with patch("ingestion_v2.field_accuracy.read_mongo_verification") as readback:
            with self.assertRaisesRegex(ValueError, "hashes must match"):
                audit_fields(self.directory, self.source, self.manifest, verify_mongo=True)
        readback.assert_not_called()

    def test_duplicate_mapping_identity_is_not_scored_as_correct(self):
        row = {"target_collection": self.target, "data": self.record}
        self.save("mapping.json", {"records": [row, row]})
        report = audit_fields(self.directory, self.source, self.manifest)
        self.assertEqual(report["mapped_accuracy"]["ambiguous"], 3)

    def test_html_shows_source_values_and_escapes_log_text(self):
        report = audit_fields(self.directory, self.source, self.manifest)
        html = render_audit_html(report, [{"stage": "mapping", "message": "<script>bad</script>"}])
        self.assertIn("$.price", html)
        self.assertIn("MongoDB read-back", html)
        self.assertIn("Processing log", html)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", html)
        self.assertNotIn("<script>bad</script>", html)


class ProgressTests(unittest.TestCase):
    def test_callback_emits_after_event_is_saved(self):
        with TemporaryDirectory() as directory, redirect_stderr(StringIO()) as stderr:
            def on_event(run_id, event):
                event_path = Path(directory) / run_id / "events.jsonl"
                self.assertEqual(json.loads(event_path.read_text())["stage"], "mapping_validation")
                _progress_line(run_id, event)

            store = LocalIngestionRunStore(directory, on_event=on_event)
            run = IngestionRun(run_id="run-a", status=RunStatus.STARTED, write_mode=WriteMode.DRY_RUN)
            store.add_event(run, "mapping_validation", "started", "Waiting for mapping proposal")
            self.assertIn("[run-a #1] mapping_validation: started", stderr.getvalue())

    def test_progress_option_is_only_for_ingestion(self):
        self.assertTrue(parse_args(["--input", "x.json", "--progress"]).progress)
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["--print-tool-schemas", "--progress"])
