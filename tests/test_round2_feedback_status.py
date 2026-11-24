from contextlib import redirect_stdout
import csv
import importlib.util
from io import StringIO
import json
from pathlib import Path
import unittest

from ingestion_v2.extraction import SUPPORTED_SUFFIXES
from review_pending_source import FORMATS, main as source_main
from run_ingestion_v2 import main as ingestion_main
from scripts.summarize_adapter_comparison import summarize


class FeedbackStatusTests(unittest.TestCase):
    def test_list_formats_is_the_live_ingestion_allowlist_and_does_not_claim_word(self):
        with redirect_stdout(StringIO()) as stream:
            self.assertEqual(ingestion_main(["--list-formats"]), 0)
        data = json.loads(stream.getvalue())
        self.assertEqual(set(data["ingestion_inputs"]), set(SUPPORTED_SUFFIXES))
        self.assertFalse(any(data["word_conversion"].values()))

    def test_pending_inventory_lists_four_sources_without_claiming_activation(self):
        with redirect_stdout(StringIO()) as stream:
            self.assertEqual(source_main(["--list"]), 0)
        result = json.loads(stream.getvalue())
        self.assertFalse(result["database_write_performed"])
        self.assertEqual({row["source_id"] for row in result["sources"]}, set(FORMATS))
        self.assertTrue(all(row["status"] == "pending" and row["next_acceptance_gate"] for row in result["sources"]))

    def test_adapter_summary_reproduces_the_saved_paired_scores(self):
        with Path("eval/adapter_comparison.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        report = summarize(rows)
        self.assertEqual(
            (report["held_out_cases"], report["base_correct"], report["adapter_correct"], report["fixed"]),
            (10, 2, 4, 2),
        )
        self.assertEqual(report["change_percentage_points"], 20.0)
        self.assertEqual(report["unchanged_incorrect"], 6)
        self.assertIn("not deployed Qwen", report["scope"])
        with self.assertRaisesRegex(ValueError, "unique case IDs"):
            summarize(rows + rows[:1])
        with self.assertRaisesRegex(ValueError, "no training overlap"):
            summarize([{**rows[0], "training_overlap": "1"}])


@unittest.skipUnless(
    importlib.util.find_spec("flask") and importlib.util.find_spec("pymongo"),
    "Flask and PyMongo are needed for the fake-service HTTP test",
)
class FeedbackHttpTests(unittest.TestCase):
    def setUp(self):
        from data_api import create_app

        class NoDbService:
            pass

        self.client = create_app(service=NoDbService(), qa_service=object()).test_client()

    def test_period_preview_calls_no_database_and_does_not_accept_wrong_view(self):
        csv_bytes = (
            "frequency,period_start,district,crop,price_unit,average_modal_price_inr,"
            "observation_count,evidence_as_of,source,data_scope\n"
            "weekly,2025-02-03,Patna,Potato,quintal,1000.50,5,2025-02-07,Fixture,Observed\n"
        )
        path = "/api/v1/mandi-period-report/preview?frequency="
        accepted = self.client.post(path + "weekly", data=csv_bytes, content_type="text/csv")
        self.assertEqual(accepted.status_code, 200)
        self.assertFalse(accepted.get_json()["database_writes"])
        self.assertEqual(self.client.post(path + "monthly", data=csv_bytes, content_type="text/csv").status_code, 400)
        self.assertEqual(self.client.post(path + "weekly", data=csv_bytes).status_code, 415)

    def test_local_dashboard_has_map_and_both_report_inputs(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        for marker in (b"leaflet@1.9.4", b'id="arwal-preset"', b'id="district-trends-form"',
                       b'data-period-preview="weekly"', b'data-period-preview="monthly"'):
            self.assertIn(marker, page.data)
