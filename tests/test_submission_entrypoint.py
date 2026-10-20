import json
import tempfile
import unittest
from pathlib import Path

from run import main, process_input


class SubmissionEntrypointTests(unittest.TestCase):
    def test_generic_json_is_processed_without_database_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "unseen.json"
            path.write_text(json.dumps([{"crop": "Rice", "value": 2}]), encoding="utf-8")
            tool, records, report = process_input(path)
        self.assertEqual(tool, "generic_json_reader")
        self.assertEqual(records[0]["crop"], "Rice")
        self.assertEqual(report, {})

    def test_csv_preserves_unseen_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "unseen.csv"
            path.write_text("place,value\nPatna,7\n", encoding="utf-8")
            tool, records, _ = process_input(path)
        self.assertEqual(tool, "python_csv_reader")
        self.assertEqual(records, [{"place": "Patna", "value": "7"}])

    def test_unsupported_extension_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.txt"
            path.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                process_input(path)

    def test_failure_writes_an_auditable_trace(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.pdf"
            output = Path(folder) / "failed.json"
            status = main(["--input", str(missing), "--output", str(output)])
            trace = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(status, 1)
        self.assertEqual(trace["status"], "failed")
        self.assertEqual(trace["events"][-1]["event"], "run_failed")
        self.assertFalse(trace["database_write"])
