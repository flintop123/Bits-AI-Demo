"""Tests for the extractor UI package: job runner, clarification pause,
API guard/validation, and the real executor over a scripted model.

No Ollama, MongoDB or network access is needed.
"""

import logging
import threading
import time
import unittest
from unittest.mock import patch

from flask import Flask
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from extractor_ui import extractor_blueprint
from extractor_ui import runner as runner_module
from extractor_ui.runner import ExtractorRunner, RunnerBusy

HEADERS = {"X-Agri-Dashboard": "1"}


def wait_for(predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class RunnerTests(unittest.TestCase):
    def test_run_collects_logs_and_completes(self):
        def executor(run, request, dry_run):
            run.log(f"hello {request}")
            run.finish(answer="done")

        runner = ExtractorRunner(executor)
        run = runner.start("go", True)
        self.assertTrue(wait_for(lambda: run.status == "completed"))
        snap = run.snapshot()
        self.assertEqual(snap["answer"], "done")
        self.assertTrue(snap["dry_run"])
        self.assertEqual(snap["logs"][0]["text"], "hello go")
        self.assertEqual(run.snapshot(after=snap["next"])["logs"], [])

    def test_executor_exception_marks_run_failed(self):
        def executor(run, request, dry_run):
            raise RuntimeError("mongo down")

        run = ExtractorRunner(executor).start("go", False)
        self.assertTrue(wait_for(lambda: run.status == "failed"))
        self.assertEqual(run.snapshot()["error"], "mongo down")

    def test_second_run_is_rejected_while_active(self):
        release = threading.Event()

        def executor(run, request, dry_run):
            release.wait(5)
            run.finish(answer="ok")

        runner = ExtractorRunner(executor)
        first = runner.start("one", False)
        with self.assertRaises(RunnerBusy):
            runner.start("two", False)
        release.set()
        self.assertTrue(wait_for(lambda: first.status == "completed"))
        runner.start("three", False)

    def test_clarification_waits_for_browser_choice(self):
        picked = []

        def executor(run, request, dry_run):
            picked.append(run.ask("Which?", [{"number": 1, "label": "A"}, {"number": 2, "label": "B"}]))
            run.finish(answer="ok")

        run = ExtractorRunner(executor).start("go", False)
        self.assertTrue(wait_for(lambda: run.status == "waiting"))
        self.assertEqual(run.snapshot()["prompt"]["options"][1]["label"], "B")
        with self.assertRaises(ValueError):
            run.answer_prompt(3)
        run.answer_prompt(2)
        self.assertTrue(wait_for(lambda: run.status == "completed"))
        self.assertEqual(picked, [2])
        with self.assertRaises(LookupError):
            run.answer_prompt(1)

    def test_clarification_cancel_and_timeout_return_none(self):
        run = runner_module.Run("go", False)
        threading.Timer(0.05, lambda: run.answer_prompt(None)).start()
        self.assertIsNone(run.ask("Which?", [{"number": 1, "label": "A"}], timeout=5))
        self.assertIsNone(runner_module.Run("go", False).ask("Which?", [], timeout=0.05))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.release = threading.Event()
        self.seen = []

        def executor(run, request, dry_run):
            self.seen.append((request, dry_run))
            run.log("started")
            self.release.wait(5)
            run.finish(answer="finished")

        app = Flask(__name__)
        app.register_blueprint(extractor_blueprint(ExtractorRunner(executor)))
        self.client = app.test_client()

    def tearDown(self):
        self.release.set()

    def post(self, path, **body):
        return self.client.post(path, json=body, headers=HEADERS)

    def test_api_requires_dashboard_header_and_same_origin(self):
        self.assertEqual(self.client.post("/extractor/api/runs", json={"request": "x"}).status_code, 403)
        response = self.client.post(
            "/extractor/api/runs", json={"request": "x"},
            headers={**HEADERS, "Origin": "http://evil.example"},
        )
        self.assertEqual(response.status_code, 403)
        remote = self.client.post(
            "/extractor/api/runs", json={"request": "x"}, headers=HEADERS,
            environ_overrides={"REMOTE_ADDR": "10.0.0.5"},
        )
        self.assertEqual(remote.status_code, 403)

    def test_page_and_assets_are_served_without_the_api_header(self):
        page = self.client.get("/extractor/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Extractor agent", page.data)
        page.close()
        for name in ("extractor.js", "extractor.css"):
            response = self.client.get(f"/extractor/assets/{name}")
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_validation(self):
        self.assertEqual(self.post("/extractor/api/runs", request="  ").status_code, 400)
        self.assertEqual(self.post("/extractor/api/runs", request="x" * 1001).status_code, 400)
        self.assertEqual(self.post("/extractor/api/runs", request="x", dry_run="yes").status_code, 400)
        self.assertEqual(self.client.get("/extractor/api/runs/nope", headers=HEADERS).status_code, 404)
        self.assertEqual(self.client.get("/extractor/api/runs/latest", headers=HEADERS).status_code, 404)

    def test_start_poll_and_busy(self):
        response = self.post("/extractor/api/runs", request=" load crops ", dry_run=True)
        self.assertEqual(response.status_code, 202)
        run_id = response.json["run_id"]
        self.assertTrue(wait_for(lambda: self.seen))
        self.assertEqual(self.seen[0], ("load crops", True))
        self.assertEqual(self.post("/extractor/api/runs", request="again").status_code, 409)

        self.assertTrue(wait_for(lambda: self.client.get(
            f"/extractor/api/runs/{run_id}", headers=HEADERS).json["logs"]))
        self.release.set()
        self.assertTrue(wait_for(lambda: self.client.get(
            f"/extractor/api/runs/{run_id}?after=1", headers=HEADERS).json["status"] == "completed"))
        latest = self.client.get("/extractor/api/runs/latest", headers=HEADERS).json
        self.assertEqual(latest["run_id"], run_id)
        self.assertEqual(latest["answer"], "finished")

    def test_choice_endpoint_rejects_when_nothing_is_waiting(self):
        run_id = self.post("/extractor/api/runs", request="x").json["run_id"]
        self.assertEqual(self.post(f"/extractor/api/runs/{run_id}/choice", choice=1).status_code, 409)


class AgentExecutorTests(unittest.TestCase):
    """The real executor over the real resolver, with a scripted model."""

    def setUp(self):
        self.calls = []
        calls = self.calls

        @tool
        def ingest_crop_statistics(instruction: str = "") -> str:
            """Load crop statistics."""
            calls.append(instruction)
            return "status=completed; dry_run=" + str("dry run" in instruction.lower())

        self.tool = ingest_crop_statistics
        logger = logging.getLogger("agent_tools.run")
        logger.setLevel(logging.INFO)
        patcher = patch("agent_tools.agent_logging.configure_logging", return_value=logger)
        patcher.start()
        self.addCleanup(patcher.stop)
        tools = patch("agent.default_tools", return_value=[self.tool])
        tools.start()
        self.addCleanup(tools.stop)

    def model(self):
        return ScriptedModel(responses=[
            AIMessage(content="Loading.", tool_calls=[
                {"name": "ingest_crop_statistics", "args": {"instruction": "load crop statistics"}, "id": "1"}]),
            AIMessage(content="Loaded crop statistics."),
        ])

    def execute(self, request, dry_run, cancel=False):
        run = runner_module.Run(request, dry_run)
        if cancel:
            def answer():
                wait_for(lambda: run.prompt is not None)
                run.answer_prompt(None)
            threading.Thread(target=answer, daemon=True).start()
        runner_module.agent_executor(run, request, dry_run, llm=self.model())
        return run

    def test_dry_run_checkbox_is_forced_onto_the_tool_call(self):
        run = self.execute("load crop statistics excel", True)
        self.assertEqual(run.answer, "Loaded crop statistics.")
        self.assertIn("dry run", self.calls[0].lower())
        texts = [line["text"] for line in run.snapshot()["logs"]]
        self.assertTrue(any("Tool result: status=completed; dry_run=True" in t for t in texts))

    def test_write_mode_leaves_instruction_alone(self):
        run = self.execute("load crop statistics excel", False)
        self.assertEqual(self.calls, ["load crop statistics"])
        texts = [line["text"] for line in run.snapshot()["logs"]]
        self.assertTrue(any("dry_run=False" in t for t in texts))

    def test_unclear_request_asks_the_browser_then_continues(self):
        run = runner_module.Run("load some data", False)
        options = {}

        def answer():
            wait_for(lambda: run.prompt is not None)
            options.update(run.prompt)
            index = next(o["number"] for o in run.prompt["options"] if "crop" in o["label"].lower())
            run.answer_prompt(index)

        threading.Thread(target=answer, daemon=True).start()
        runner_module.agent_executor(run, "load some data", False, llm=self.model())
        self.assertTrue(options["options"])
        self.assertEqual(run.answer, "Loaded crop statistics.")

    def test_cancelling_the_question_stops_without_running_a_tool(self):
        run = self.execute("load some data", False, cancel=True)
        self.assertEqual(run.answer, "No tool was selected for this request.")
        self.assertEqual(self.calls, [])

    def test_typed_request_that_resolves_is_not_overridden(self):
        run = self.execute("load crop statistics excel", False)
        doc = run.document()
        self.assertFalse(doc["is_human_input_overridden"])
        self.assertIsNone(doc["overridden_input"])
        self.assertEqual(doc["tool"], "ingest_crop_statistics")
        self.assertEqual(doc["human_input"], "load crop statistics excel")

    def test_option_picked_in_popup_is_recorded_as_override(self):
        run = runner_module.Run("load some data", False)

        def answer():
            wait_for(lambda: run.prompt is not None)
            index = next(o["number"] for o in run.prompt["options"] if "crop" in o["label"].lower())
            run.answer_prompt(index)

        threading.Thread(target=answer, daemon=True).start()
        runner_module.agent_executor(run, "load some data", False, llm=self.model())
        doc = run.document()
        self.assertEqual(doc["human_input"], "load some data")
        self.assertTrue(doc["is_human_input_overridden"])
        self.assertIn("Load:", doc["overridden_input"])


def project(doc, projection):
    """Mongo-style projection: inclusion (with optional _id exclusion) or
    exclusion-only."""
    if not projection:
        return dict(doc)
    included = {k for k, v in projection.items() if v and k != "_id"}
    if included:
        out = {k: v for k, v in doc.items() if k in included}
        if projection.get("_id", 1):
            out["_id"] = doc["_id"]
        return out
    return {k: v for k, v in doc.items() if projection.get(k, 1)}


class FakeCursor:
    """Sorts and pages the full documents, projecting only on iteration (as
    MongoDB does), so a sort key can be a field the projection hides."""

    def __init__(self, docs, projection=None):
        self.docs = docs
        self.projection = projection

    def sort(self, keys):
        for key, direction in reversed(keys):
            self.docs = sorted(self.docs, key=lambda d: d.get(key), reverse=direction < 0)
        return self

    def skip(self, n):
        self.docs = self.docs[n:]
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    def __iter__(self):
        return iter([project(d, self.projection) for d in self.docs])


class FakeCollection:
    def __init__(self):
        self.docs = {}
        self.indexes = []

    def create_index(self, spec):
        self.indexes.append(spec)

    def update_one(self, query, update, upsert=False):
        doc = self.docs.setdefault(query["_id"], {"_id": query["_id"]})
        doc.update(update["$set"])

    def count_documents(self, query):
        return len(self.docs)

    def find(self, query, projection=None):
        return FakeCursor(list(self.docs.values()), projection)

    def find_one(self, query, projection=None):
        doc = self.docs.get(query["_id"])
        return None if doc is None else project(doc, projection)


class FakeHistory:
    def __init__(self, fail=False):
        self.saved = []
        self.fail = fail

    def save(self, document):
        if self.fail:
            raise RuntimeError("mongo down")
        self.saved.append(document)

    def page(self, page=1):
        return {"items": self.saved, "page": page, "pages": 1, "page_size": 10, "total": len(self.saved)}

    def get(self, run_id):
        return next((d for d in self.saved if d["run_id"] == run_id), None)


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        from extractor_ui.history import RunHistoryStore

        self.collection = FakeCollection()
        self.store = RunHistoryStore(lambda: {"extractor_runs": self.collection})

    def doc(self, n):
        return {
            "run_id": f"r{n:02d}", "human_input": f"input {n}",
            "is_human_input_overridden": False, "overridden_input": None,
            "dry_run": False, "tool": "t", "status": "completed",
            "started_at": f"2026-01-01T00:00:{n:02d}+00:00",
            "finished_at": None, "logs": [{"time": "00:00:00", "text": "x"}],
            "result": "ok", "error": None,
        }

    def test_pages_are_ten_newest_first_without_logs(self):
        for n in range(25):
            self.store.save(self.doc(n))
        first = self.store.page(1)
        self.assertEqual((first["total"], first["pages"], first["page_size"]), (25, 3, 10))
        self.assertEqual([i["run_id"] for i in first["items"]][:2], ["r24", "r23"])
        self.assertEqual(len(first["items"]), 10)
        self.assertNotIn("logs", first["items"][0])
        self.assertEqual(len(self.store.page(3)["items"]), 5)
        self.assertEqual(self.store.page(99)["page"], 3)
        self.assertEqual(self.store.page(0)["page"], 1)

    def test_empty_history_and_detail_lookup(self):
        self.assertEqual(self.store.page(1)["items"], [])
        self.assertIsNone(self.store.get("missing"))
        self.store.save(self.doc(1))
        detail = self.store.get("r01")
        self.assertEqual(detail["logs"][0]["text"], "x")
        self.assertNotIn("_id", detail)

    def test_save_is_idempotent_and_indexes_once(self):
        self.store.save(self.doc(1))
        self.store.save(self.doc(1))
        self.assertEqual(self.store.page(1)["total"], 1)
        self.assertEqual(len(self.collection.indexes), 1)


class HistoryPersistenceTests(unittest.TestCase):
    def test_finished_run_is_saved_before_it_is_visible_as_completed(self):
        history = FakeHistory()

        def executor(run, request, dry_run):
            run.log("step")
            run.overridden_input = "Load: Crop area. Dry run."
            run.tool = "ingest_crop_statistics"
            run.finish(answer="done")

        runner = ExtractorRunner(executor, history=history)
        run = runner.start("load some data", True)
        self.assertTrue(wait_for(lambda: run.status == "completed"))
        self.assertTrue(run.snapshot()["history_saved"])
        saved = history.saved[0]
        self.assertEqual(saved["human_input"], "load some data")
        self.assertTrue(saved["is_human_input_overridden"])
        self.assertEqual(saved["overridden_input"], "Load: Crop area. Dry run.")
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["result"], "done")
        self.assertEqual(saved["logs"][0]["text"], "step")
        self.assertTrue(saved["dry_run"])

    def test_failed_run_is_saved_with_error(self):
        history = FakeHistory()

        def executor(run, request, dry_run):
            raise RuntimeError("boom")

        run = ExtractorRunner(executor, history=history).start("go", False)
        self.assertTrue(wait_for(lambda: run.status == "failed"))
        self.assertEqual(history.saved[0]["status"], "failed")
        self.assertEqual(history.saved[0]["error"], "boom")
        self.assertFalse(history.saved[0]["is_human_input_overridden"])

    def test_history_failure_does_not_lose_the_result(self):
        def executor(run, request, dry_run):
            run.finish(answer="done")

        run = ExtractorRunner(executor, history=FakeHistory(fail=True)).start("go", False)
        self.assertTrue(wait_for(lambda: run.status == "completed"))
        snap = run.snapshot()
        self.assertEqual(snap["answer"], "done")
        self.assertFalse(snap["history_saved"])
        self.assertTrue(any("Could not save run history" in l["text"] for l in snap["logs"]))

    def test_history_endpoints(self):
        history = FakeHistory()
        history.saved.append({"run_id": "abc", "human_input": "x", "logs": []})
        app = Flask(__name__)
        app.register_blueprint(extractor_blueprint(ExtractorRunner(lambda r, q, d: None, history=history)))
        client = app.test_client()
        page = client.get("/extractor/api/history?page=1", headers=HEADERS)
        self.assertEqual(page.json["total"], 1)
        self.assertEqual(client.get("/extractor/api/history/abc", headers=HEADERS).json["run_id"], "abc")
        self.assertEqual(client.get("/extractor/api/history/zzz", headers=HEADERS).status_code, 404)
        self.assertEqual(client.get("/extractor/api/history").status_code, 403)

    def test_history_endpoints_without_a_store(self):
        app = Flask(__name__)
        app.register_blueprint(extractor_blueprint(ExtractorRunner(lambda r, q, d: None)))
        response = app.test_client().get("/extractor/api/history", headers=HEADERS)
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()