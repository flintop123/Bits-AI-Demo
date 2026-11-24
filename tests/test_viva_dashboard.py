import copy
from io import BytesIO
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

import pymupdf
from bson import BSON
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from data_api import create_app
from services.viva_dashboard import COLLECTION, ReactDashboard, ReactNoEvidence, VivaUploadStore


HEADERS = {"X-Agri-Dashboard": "1"}
URL = "/api/v1/viva"
TEXT = (
    "The independent Bihar viva sample documents drainage and seasonal crop "
    "planning. This sentence is directly extracted and verified by source page."
)


def pdf_bytes(pages=2, *, blank=False):
    with pymupdf.open() as document:
        for number in range(1, pages + 1):
            page = document.new_page()
            if not blank:
                page.insert_textbox((60, 60, 530, 230), f"Source page {number}: {TEXT}")
        return document.tobytes()


class CollectionDouble:
    def __init__(self):
        self.rows = {}
        self.writes = 0
        self.reads = 0

    def update_one(self, query, mutation, *, upsert):
        assert upsert and set(mutation) == {"$setOnInsert"}
        self.writes += 1
        key = query["_id"]
        row = BSON.encode({"_id": key, **mutation["$setOnInsert"]}).decode()
        self.rows.setdefault(key, row)

    def find_one(self, query):
        self.reads += 1
        return copy.deepcopy(self.rows.get(query["_id"]))


class DatabaseDouble:
    name = "bihar_agriculture"

    def __init__(self):
        self.uploads = CollectionDouble()

    def __getitem__(self, name):
        assert name == COLLECTION, "The upload store must not access the curated corpus"
        return self.uploads


class UploadTests(TestCase):
    def setUp(self):
        self.db = DatabaseDouble()
        self.store = VivaUploadStore(self.db)
        self.client = create_app(Mock(), Mock(), viva_upload_store=self.store).test_client()

    def preview(self, raw=None, name="Demo document.pdf"):
        return self.client.post(
            URL + "/uploads/preview", headers=HEADERS,
            data={"document": (BytesIO(pdf_bytes() if raw is None else raw), name)},
        )

    def test_dashboard_renders_both_workflows(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        for label in (b"ReAct agent", b"Upload and verify a PDF", b"Save to MongoDB",
                      b"viva-dashboard.js"):
            self.assertIn(label, response.data)

    def test_actual_pdf_preview_save_verify_and_reopen(self):
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        result = response.json
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["source_file"], "Demo document.pdf")
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual([row["page_number"] for row in result["records"]], [1, 2])
        self.assertEqual([row["chunk_index"] for row in result["records"]], [0, 0])
        self.assertIn("Source page 2:", result["records"][1]["content"])
        self.assertEqual(self.db.uploads.writes, 0)
        self.assertEqual(self.db.uploads.reads, 0)

        location = URL + "/uploads/" + result["run_id"]
        failed = self.client.post(location + "/save", headers=HEADERS,
                                  json={"records": [{"content": "replacement"}]})
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(self.db.uploads.writes, 0)

        saved = self.client.post(location + "/save", headers=HEADERS)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json["status"], "verified")
        self.assertEqual(saved.json["saved_count"], 2)
        self.assertEqual(saved.json["records"], result["records"])
        self.assertEqual(saved.json["collection"], COLLECTION)
        self.assertEqual(self.db.uploads.reads, 1)
        self.assertEqual(self.client.post(location + "/save", headers=HEADERS).json, saved.json)
        self.assertEqual(len(self.db.uploads.rows), 1)

        # Reopening neither depends on the original browser nor an in-memory draft.
        reopened = create_app(Mock(), Mock(), viva_upload_store=self.store).test_client()
        self.assertEqual(reopened.get(location, headers=HEADERS).json, saved.json)
        self.db.uploads.rows[result["run_id"]]["records"][0]["content"] = "changed"
        self.assertEqual(reopened.get(location, headers=HEADERS).status_code, 409)

    def test_invalid_extension_invalid_content_excess_pages_and_size(self):
        for raw, name, status in (
            (b"not a PDF", "fake.pdf", 400),
            (b"%PDF-1.7\n", "broken.pdf", 400),
            (b"%PDF-1.7", "payload.exe", 400),
            (pdf_bytes(26, blank=True), "long.pdf", 400),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.preview(raw, name).status_code, status)
        with patch("viva_api.MAX_PDF_BYTES", 1024):
            self.assertEqual(self.preview(b"%PDF-" + b"x" * 1024).status_code, 413)
        self.assertEqual(self.db.uploads.writes, 0)

    def test_empty_preview_cannot_be_saved(self):
        from tools.pdf_extractor.agriculture_pdf_extractor import AgriculturePDFExtractor

        with patch.object(AgriculturePDFExtractor, "_ocr_page", return_value=""):
            response = self.preview(pdf_bytes(1, blank=True))
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["valid_count"], 0)
        path = f"{URL}/uploads/{response.json['run_id']}/save"
        self.assertEqual(self.client.post(path, headers=HEADERS).status_code, 400)
        self.assertEqual(self.db.uploads.writes, 0)

    def test_only_local_dashboard_requests_may_publish(self):
        path = f"{URL}/uploads/{uuid4()}/save"
        for kwargs in (
            {},
            {"headers": {**HEADERS, "Origin": "http://localhost:8000"}},
            {"headers": HEADERS, "base_url": "http://example.test"},
            {"headers": HEADERS, "environ_overrides": {"REMOTE_ADDR": "192.0.2.5"}},
        ):
            with self.subTest(kwargs=kwargs):
                response = self.client.post(path, **kwargs)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertEqual(self.db.uploads.writes, 0)


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        assert [tool.name for tool in tools] == ["ask_agriculture_question"]
        return self


class ReactTests(TestCase):
    def test_react_returns_grounded_tool_evidence_and_preserves_original_request(self):
        qa = Mock()
        evidence = {"answer": "Verified answer.", "sources": [{"page_number": 3}],
                    "records": [{"content": "Evidence"}]}
        qa.ask.return_value = evidence
        model = ScriptedModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "ask_agriculture_question", "args": {}, "id": "call-1",
            }]),
            AIMessage(content="Unverified model rewrite."),
        ])
        question = "मखाना निर्यात का मूल हिन्दी शीर्षक दिखाएँ।"
        app = create_app(Mock(), qa, viva_react=ReactDashboard(qa, llm=model))
        response = app.test_client().post(URL + "/react", headers=HEADERS, json={
            "question": question, "answer_language": "hi",
        })
        self.assertEqual(response.status_code, 200, response.json)
        qa.ask.assert_called_once_with(question, answer_language="hi")
        self.assertEqual(response.json["answer"], evidence["answer"])
        self.assertEqual(response.json["sources"], evidence["sources"])
        self.assertTrue(response.json["react"]["tool_called"])

    def test_react_rejects_unsupported_and_never_returns_unverified_direct_answer(self):
        qa = Mock()
        react = ReactDashboard(qa, llm=ScriptedModel(responses=[AIMessage(content="Guess.")]))
        with self.assertRaisesRegex(ValueError, "Upload a PDF"):
            react.ask("load mandi data via API", "auto")
        with self.assertRaises(ReactNoEvidence):
            react.ask("What was the rice price?", "auto")
        qa.ask.assert_not_called()
