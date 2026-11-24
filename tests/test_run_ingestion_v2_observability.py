from contextlib import redirect_stderr
from io import StringIO
import unittest

from run_ingestion_v2 import parse_args


class IngestionObservabilityCliTests(unittest.TestCase):
    def test_existing_run_report_mode_does_not_require_input(self):
        args = parse_args(["--report-run", "run-123", "--verify-mongo"])
        self.assertEqual(args.report_run, "run-123")
        self.assertTrue(args.verify_mongo)

    def test_comparison_mode_accepts_two_run_ids(self):
        args = parse_args(["--compare-runs", "before", "after"])
        self.assertEqual(args.compare_runs, ["before", "after"])

    def test_conflicting_modes_are_rejected(self):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                parse_args([
                    "--input", "file.json", "--report-run", "run-123"
                ])


if __name__ == "__main__":
    unittest.main()
