import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ("daily_mandi_api_agent", "crop_statistics_excel_agent", "multilingual_pdf_agent", "grounded_qa_agent")


class Phase2ProtocolComplianceTests(unittest.TestCase):
    def test_exact_required_paths_exist(self):
        paths = ["docs/source_agent_map.csv", "docs/challenge.md", "eval/run_eval.py", "eval/phase2_metrics.csv", "logs/automation_log.csv", "db/schema.sql", "db/dictionary.md", "db/dump", "eval/adapter_comparison.csv", "data/manifest.csv", "run.py"]
        for path in paths:
            self.assertTrue((ROOT / path).exists(), path)

    def test_four_agents_have_cards_and_ten_checked_cases(self):
        total = 0
        for agent in AGENTS:
            self.assertTrue((ROOT / "docs" / "agents" / f"{agent}.md").is_file())
            cases = json.loads((ROOT / "eval" / "cases" / f"{agent}.json").read_text(encoding="utf-8"))
            refs = json.loads((ROOT / "eval" / "reference" / f"{agent}.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(cases), 10)
            self.assertEqual({x["case_id"] for x in cases}, {x["case_id"] for x in refs})
            self.assertTrue(all(x.get("checked_against_source") is True for x in refs))
            total += len(cases)
        self.assertGreaterEqual(total, 30)

    def test_metric_header_matches_faculty_template(self):
        with (ROOT / "eval" / "phase2_metrics.csv").open(encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle))
        self.assertEqual(header, ["metric_id", "scope", "numerator", "denominator", "value", "n_cases", "evaluator_or_script", "notes"])

    def test_source_inventory_has_done_and_pending_work(self):
        with (ROOT / "docs" / "source_agent_map.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 10)
        self.assertEqual(sum(x["status"] == "done" for x in rows), 6)
        self.assertEqual(sum(x["status"] == "pending" for x in rows), 4)

    def test_schema_ddl_loads_in_sqlite(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            connection.close()
        self.assertEqual(tables, {"mandi_prices", "crop_statistics", "agriculture_documents", "mandi_locations"})

    def test_sample_dump_loads_into_relational_mirror(self):
        from db.load_dump import load_sqlite
        records = {
            "mandi_prices": [{"source_record_id":"m1","district":"अरवल","market":"अरवल","date":"2026-10-18","crop":"आलू","source_url":"https://example.invalid","unit":"quintal"}],
            "crop_statistics": [{"crop":"Rice","season":"Total","year":"2024-25","source_file":"crop.xlsx","source_row":11,"production_unit":"tonne"}],
            "agriculture_documents": [{"content_hash":"h1","content":"text","page_number":1,"source_url":"https://example.invalid","source_file":"report.pdf"}],
            "mandi_locations": [{"market_code":"1","market_name":"अरवल","district_name":"अरवल","location":{"type":"Point","coordinates":[84.66,25.24]},"verification_status":"verified","location_precision":"market_locality_centroid","coordinate_source_url":"https://example.invalid"}],
        }
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "mirror.sqlite"
            load_sqlite(records, destination)
            connection = sqlite3.connect(destination)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mandi_prices").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mandi_locations").fetchone()[0], 1)
            finally:
                connection.close()

    def test_adapter_training_questions_do_not_overlap_holdout(self):
        import hashlib
        import re
        def digest(value):
            value = re.sub(r"\s+", " ", value).strip().casefold()
            return hashlib.sha256(value.encode("utf-8")).hexdigest()
        training = json.loads((ROOT / "eval/training/intent_router_train.json").read_text(encoding="utf-8"))
        cases = json.loads((ROOT / "eval/cases/grounded_qa_agent.json").read_text(encoding="utf-8"))
        train_hashes = {digest(x["question"]) for x in training}
        case_hashes = {digest(x["input"]["question"]) for x in cases}
        self.assertTrue(train_hashes.isdisjoint(case_hashes))

    def test_metric_evaluator_does_not_treat_reference_presence_as_correctness(self):
        from eval.run_eval import aggregate_results
        result = {
            "agent_id": "crop_statistics_excel_agent",
            "source_group": "Database",
            "field_checks": [True, False],
            "provenance_checks": [True],
            "grounding_checks": [True, False],
            "selected_tool": "pandas_excel_extractor",
            "expected_tool": "pandas_excel_extractor",
            "tool_input_correct": True,
            "trajectory_match": True,
            "task_complete": True,
        }
        rows = aggregate_results([result])
        agent_m3 = next(x for x in rows if x["metric_id"] == "M3" and x["scope"] == "crop_statistics_excel_agent")
        self.assertEqual(agent_m3["value"], 0.5)
