import copy
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

import pymupdf
from bson import BSON
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from data_api import create_app
from services.viva_dashboard import COLLECTION, ReactDashboard, ReactNoEvidence, VivaUploadStore, _record_bytes
from services.viva_evidence import PageAnchors, answer_from_pdf


HEADERS = {"X-Agri-Dashboard": "1"}
URL = "/api/v1/viva"
TEXT = (
    "The independent Bihar viva sample documents drainage and seasonal crop "
    "planning. This sentence is directly extracted and verified by source page."
)
TABLES = [{
    "profile": "bihar_des_final_2024_25_crop_page3", "page_number": 3,
    "context": {"geography": {"text": "Jurisdiction: Bihar", "page": 2},
                "period": {"text": "2024-25", "page": 3},
                "estimate_stage": {"text": "Final Estimation", "page": 3}},
    "cells": [
        {"page_number": 3, "row": "Wheat", "column": column, "unit": unit,
         "value": value, "printed_text": printed,
         "source_anchor": {"kind": "verified_table_cell", "boxes": [[.5, .4, .64, .45]]}}
        for column, unit, value, printed in (
            ("Area (Hectare)", "Hectare", "2340356", "23,40,356"),
            ("Production (MT)", "MT", "7826998", "78,26,998"),
            ("Yield (KG/Hectare)", "KG/Hectare", "3344", "3,344"),
        )
    ],
}]


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
        inserted = key not in self.rows
        self.rows.setdefault(key, row)
        return SimpleNamespace(upserted_id=key if inserted else None)

    def find_one(self, query, *, sort=None):
        self.reads += 1
        if "_id" in query:
            return copy.deepcopy(self.rows.get(query["_id"]))
        return copy.deepcopy(next((row for row in self.rows.values()
                                  if row["source_sha256"] == query["source_sha256"]), None))


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
        raw = pdf_bytes()
        response = self.preview(raw)
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
        self.assertEqual(result["records"][1]["source_anchor"]["kind"], "exact_passage")
        page = self.client.get(location + "/evidence/2/0", headers=HEADERS)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["X-Source-Anchor"], "exact_passage")
        self.assertTrue(page.data.startswith(b"\x89PNG"))
        quote = self.client.get(location + "/evidence/2/0", headers=HEADERS,
                                query_string={"quote": "documents drainage and seasonal crop planning."})
        self.assertEqual(quote.headers["X-Source-Anchor"], "exact_quote")
        wrong_quote = self.client.get(location + "/evidence/2/0", headers=HEADERS,
                                      query_string={"quote": "There are 120 imaginary fields."})
        self.assertEqual(wrong_quote.status_code, 400)
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
        self.assertEqual(self.db.uploads.reads, 2)  # fingerprint lookup and MongoDB read-back
        self.assertFalse(saved.json["already_saved"])
        retry = self.client.post(location + "/save", headers=HEADERS).json
        self.assertEqual(retry["run_id"], saved.json["run_id"])
        self.assertTrue(retry["already_saved"])
        duplicate_id = self.preview(raw, "Same bytes, renamed.pdf").json["run_id"]
        repeated = self.client.post(f"{URL}/uploads/{duplicate_id}/save", headers=HEADERS).json
        self.assertEqual(repeated["run_id"], saved.json["run_id"])
        self.assertTrue(repeated["already_saved"])
        self.assertFalse(repeated["preview_matches_saved_passages"])
        self.assertEqual(len(self.db.uploads.rows), 1)
        self.assertEqual(self.db.uploads.writes, 1)

        # Reopening neither depends on the original browser nor an in-memory draft.
        reopened = create_app(Mock(), Mock(), viva_upload_store=self.store).test_client()
        saved_location = URL + "/uploads/" + saved.json["run_id"]
        reopened_result = reopened.get(saved_location, headers=HEADERS).json
        self.assertEqual(reopened_result["records"], saved.json["records"])
        self.assertFalse(reopened_result["source_available"])
        self.assertEqual(reopened.get(saved_location + "/evidence/1/0", headers=HEADERS).status_code, 404)
        wrong = reopened.post(saved_location + "/attach", headers=HEADERS, data={
            "document": (BytesIO(pdf_bytes(1)), "Original.pdf"),
        })
        self.assertEqual(wrong.status_code, 409)
        right = reopened.post(saved_location + "/attach", headers=HEADERS, data={
            "document": (BytesIO(raw), "Original.pdf"),
        })
        self.assertTrue(right.json["source_available"])
        self.assertEqual(reopened.get(saved_location + "/evidence/1/0", headers=HEADERS).status_code, 200)
        self.db.uploads.rows[saved.json["run_id"]]["records"][0]["content"] = "changed"
        self.assertEqual(reopened.get(saved_location, headers=HEADERS).status_code, 409)

    def test_ask_route_reads_only_the_verified_run(self):
        draft = self.preview().json
        path = f"{URL}/uploads/{draft['run_id']}"
        question = {"question": "What does this document say about drainage?"}
        self.assertEqual(self.client.post(path + "/ask", headers=HEADERS, json=question).status_code, 404)
        saved = self.client.post(path + "/save", headers=HEADERS).json
        with patch("viva_api.answer_from_pdf", return_value={"status": "answered"}) as ask:
            answered = self.client.post(f"{URL}/uploads/{saved['run_id']}/ask", headers=HEADERS, json=question)
        self.assertEqual(answered.status_code, 200)
        self.assertEqual(ask.call_args.args[1]["records"], saved["records"])
        self.assertEqual(self.db.uploads.writes, 1)

    def test_bilingual_table_answer_links_to_exact_cell_and_never_writes(self):
        with patch("services.viva_dashboard.known_table_evidence", return_value=(TABLES, [])):
            draft = self.preview(pdf_bytes(3)).json
        saved = self.client.post(f"{URL}/uploads/{draft['run_id']}/save", headers=HEADERS).json
        path = f"{URL}/uploads/{saved['run_id']}"
        request = {"question": "बिहार में 2024–25 में गेहूँ का उत्पादन कितना था?", "answer_language": "en"}
        with patch("services.viva_evidence.OllamaClient", side_effect=AssertionError("Model should not run")):
            response = self.client.post(path + "/ask", headers=HEADERS, json=request)
        self.assertEqual(response.status_code, 200, response.json)
        result = response.json
        self.assertEqual((result["method"], result["answer_language"]), ("verified_table", "en"))
        cell = result["table_cells"][0]
        self.assertEqual(cell["display_value"], "7,826,998")
        self.assertEqual((cell["page_number"], cell["unit"], cell["printed_text"]), (3, "MT", "78,26,998"))
        evidence = self.client.get(path + f"/table-evidence/{cell['table_index']}/{cell['cell_index']}",
                                   headers=HEADERS)
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(evidence.headers["X-Source-Anchor"], "verified_table_cell")
        self.assertEqual(self.db.uploads.writes, 1)
        self.assertEqual(self.client.post(path + "/ask", headers=HEADERS,
                                          json={**request, "answer_language": "xx"}).status_code, 400)
        self.db.uploads.rows[saved["run_id"]]["tables"][0]["cells"][1]["value"] = "1"
        self.assertEqual(self.client.post(path + "/ask", headers=HEADERS, json=request).status_code, 409)

    def test_duplicate_reuses_legacy_run_without_mutation(self):
        preview = self.preview().json
        previous_id = str(uuid4())
        records = [{key: value for key, value in row.items() if key != "source_anchor"}
                   for row in preview["records"]]
        previous = {
            **{key: value for key, value in preview.items()
               if key not in {"tables", "status", "collection", "source_available"}},
            "_id": previous_id, "run_id": previous_id, "records": records,
            "records_sha256": sha256(_record_bytes(records)).hexdigest(), "saved_at": "2026-11-19",
        }
        self.db.uploads.rows[previous_id] = copy.deepcopy(previous)
        result = self.client.post(f"{URL}/uploads/{preview['run_id']}/save", headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertTrue(result.json["already_saved"])
        self.assertEqual(result.json["run_id"], previous_id)
        self.assertEqual(self.db.uploads.rows[previous_id], previous)
        self.assertEqual(self.db.uploads.writes, 0)

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


class SourceEvidenceTests(TestCase):
    def test_reviewed_cell_answers_bypass_ocr_and_model(self):
        saved = {"run_id": "test", "source_file": "report.pdf",
                 "records": [{"page_number": 8, "chunk_index": 0,
                              "content": "Wheat 2024-25 OCR yield 8,844."}],
                 "tables": TABLES}
        model = Mock()
        for question, language, values in (
            ("What was Bihar’s wheat production in 2024–25?", "en", ["7,826,998"]),
            ("How much wheat did Bihar produce in 2024-2025?", "en", ["7,826,998"]),
            ("बिहार में २०२४–२५ में गेहूँ का उत्पादन कितना था? उत्तर अंग्रेज़ी में दें।", "en", ["7,826,998"]),
            ("बिहार में 2024–25 में गेहूं का उत्पादन और उपज कितनी थी?", "hi", ["78,26,998", "3,344"]),
            ("Wheat area and yield in 2024–25", "en", ["2,340,356", "3,344"]),
        ):
            with self.subTest(question=question):
                result = answer_from_pdf(question, saved, llm=model)
                self.assertEqual((result["status"], result["answer_language"]), ("answered", language))
                self.assertEqual([cell["display_value"] for cell in result["table_cells"]], values)
                self.assertEqual(result["citations"], [])
        model.chat_json.assert_not_called()

    def test_table_lookup_rejects_unproved_or_ambiguous_scope(self):
        saved = {"run_id": "test", "source_file": "report.pdf", "records": [], "tables": TABLES}
        model = Mock()
        for question in (
            "What was wheat production in Bihar in 2023–24?",
            "What was wheat production in Bihar in 2024–25 and 2023–24?",
            "What was the wheat production in Patna?",
            "How much was wheat production in the winter season?",
            "What was the wheat or sorghum production in Bihar?",
            "What was the wheat production in Bihar in 2024–25 in lakh tonnes?",
            "What was Bihar’s wheat outlay in 2024–25?",
        ):
            with self.subTest(question=question):
                result = answer_from_pdf(question, saved, llm=model)
                self.assertEqual(result["status"], "unsupported")
                self.assertNotIn("table_cells", result)
        result = answer_from_pdf("What was wheat production?", {**saved, "tables": TABLES * 2}, llm=model)
        self.assertEqual(result["status"], "unsupported")
        model.chat_json.assert_not_called()

    def test_a_shared_year_is_not_a_passage_match(self):
        saved = {"run_id": "test", "source_file": "report.pdf",
                 "records": [{"page_number": 1, "chunk_index": 0, "content": "Agriculture 2024-25"}]}
        model = Mock()
        result = answer_from_pdf("बिहार में 2024–25 में गेहूँ का उत्पादन कितना था?", saved, llm=model)
        self.assertEqual(result["status"], "unsupported")
        self.assertNotIn("matches", result)
        model.chat_json.assert_not_called()

    def test_ambiguous_text_never_gets_a_highlight(self):
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((60, 70), "Repeated sentence with identical words.")
            page.insert_text((60, 105), "Repeated sentence with identical words.")
            result = PageAnchors(page).locate("Repeated sentence with identical words.")
        self.assertEqual(result, {"kind": "page_only", "boxes": []})

    def test_rotated_page_retains_valid_normalized_highlight_coordinates(self):
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((70, 110), "An exact highlight on a rotated page.")
            page.set_rotation(90)
            result = PageAnchors(page).locate("An exact highlight on a rotated page.")
        self.assertEqual(result["kind"], "exact_passage")
        x0, y0, x1, y1 = result["boxes"][0]
        self.assertTrue(0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1)

    def test_answer_requires_real_quote_from_selected_passage(self):
        record = {"page_number": 3, "chunk_index": 1,
                  "content": "The documented drainage programme served 12 districts."}
        saved = {"run_id": "test", "source_file": "report.pdf", "records": [record]}
        question = "Which districts were covered by the drainage programme?"
        model = Mock()
        model.chat_json.return_value = {"citations": [
            {"evidence_id": 1, "quote": "programme served 120 districts."},
            {"evidence_id": 3, "quote": record["content"]},
        ]}
        self.assertEqual(answer_from_pdf(question, saved, llm=model)["status"], "unsupported")
        model.chat_json.return_value = {"citations": [
            {"evidence_id": 1, "quote": record["content"]},
        ]}
        result = answer_from_pdf(question, saved, llm=model)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["citations"][0]["quote"], record["content"])
        self.assertEqual(result["citations"][0]["page_number"], 3)


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
