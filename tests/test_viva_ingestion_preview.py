from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from data_api import create_app
from phase2 import agents
from services.viva_dashboard import ReactDashboard
from services.viva_ingestion_preview import run_document_ingestion_preview

from test_viva_dashboard import HEADERS, URL, pdf_bytes


TOOL = "preview_uploaded_agriculture_document"


class PreviewCallingModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        assert [tool.name for tool in tools] == [TOOL]
        assert tools[0].args == {}, "The model must not choose input parameters"
        return self


class IngestionPreviewTests(TestCase):
    def client_with_model(self, *messages):
        self.qa = Mock()
        self.store = Mock()
        react = ReactDashboard(self.qa, llm=PreviewCallingModel(responses=list(messages)))
        return create_app(Mock(), self.qa, viva_react=react, viva_upload_store=self.store).test_client()

    @staticmethod
    def upload(client, raw):
        return client.post(URL + "/uploads/preview", headers=HEADERS,
                           data={"document": (BytesIO(raw), "examiner.pdf")})

    @patch("ingest_agriculture_pdf.urlopen", side_effect=AssertionError("network access"))
    @patch("conn.agriculture_documents_mongodb.AgricultureDocumentsMongo",
           side_effect=AssertionError("database connection"))
    def test_react_endpoint_calls_real_document_agent_once_without_downloads_or_writes(self, database, network):
        # Try to override the dry-run argument and file with a model-supplied
        # path/URL. The zero-argument server tool must never use these values.
        call = {"name": TOOL, "args": {"dry_run": False, "url": "https://example.test/other.pdf",
                                      "path": "C:/not-the-upload.pdf"}, "id": "preview-1"}
        client = self.client_with_model(AIMessage(content="", tool_calls=[
            call, {**call, "id": "preview-2"},
        ]))
        raw = pdf_bytes(pages=2)
        preview = self.upload(client, raw)
        self.assertEqual(preview.status_code, 200, preview.json)
        key = preview.json["run_id"]
        execute = agents.AgricultureDocumentsSourceAgent.execute
        with patch.object(agents.AgricultureDocumentsSourceAgent, "execute",
                          autospec=True, side_effect=execute) as spy:
            response = client.post(f"{URL}/uploads/{key}/react-preview", headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json["react"], {"tool": TOOL, "tool_called": True})
        self.assertEqual(response.json["source_sha256"], sha256(raw).hexdigest())
        self.assertEqual(response.json["agent_id"], "multilingual_pdf_agent")
        self.assertEqual(response.json["extractor"], "pypdf_tesseract_extractor")
        self.assertEqual(response.json["pages_requested"], 2)
        self.assertEqual(response.json["pages_extracted"], 2)
        self.assertEqual(response.json["chunks_processed"], 2)
        self.assertTrue(response.json["dry_run"])
        self.assertFalse(response.json["database_writes"])
        self.assertEqual(spy.call_count, 1)
        self.assertTrue(spy.call_args.kwargs["dry_run"])
        staged_agent = spy.call_args.args[0]
        self.assertFalse(staged_agent.download_directory.exists(), "Temporary PDF must be removed")
        self.assertIsNone(staged_agent.database)
        database.assert_not_called()
        network.assert_not_called()
        self.store.assert_not_called()
        self.qa.ask.assert_not_called()

    def test_does_not_report_tool_call_if_model_did_not_call_it(self):
        client = self.client_with_model(AIMessage(content="I already finished the preview."))
        key = self.upload(client, pdf_bytes()).json["run_id"]
        with patch("phase2.agents.AgricultureDocumentsSourceAgent.execute") as real:
            response = client.post(f"{URL}/uploads/{key}/react-preview", headers=HEADERS)
        self.assertEqual(response.status_code, 422, response.json)
        self.assertNotIn("react", response.json)
        real.assert_not_called()
        self.store.assert_not_called()

    def test_only_same_origin_active_server_draft_accepted(self):
        client = self.client_with_model(AIMessage(content="Not invoked."))
        key = self.upload(client, pdf_bytes()).json["run_id"]
        path = f"{URL}/uploads/{key}/react-preview"
        self.assertEqual(client.post(path).status_code, 403)
        self.assertEqual(client.post(path, headers={**HEADERS, "Origin": "https://example.test"}).status_code, 403)
        self.assertEqual(client.post(path, headers=HEADERS, json={"path": "my.pdf"}).status_code, 400)
        self.assertEqual(client.post(path + "?url=https://example.test", headers=HEADERS).status_code, 400)
        self.assertEqual(client.post(f"{URL}/uploads/{uuid4()}/react-preview", headers=HEADERS).status_code, 404)
        self.store.assert_not_called()

    @patch("ingest_agriculture_pdf.urlopen", side_effect=AssertionError("network access"))
    def test_lost_private_cache_fails_before_network_handler(self, network):
        raw = pdf_bytes(pages=1)
        draft = {"page_count": 1, "source_sha256": sha256(raw).hexdigest(),
                 "source_file": "original.pdf"}
        real_extract = agents.extract_source

        def lose_file(source, *, download_directory):
            (Path(download_directory) / source["filename"]).unlink()
            return real_extract(source, download_directory=download_directory)

        with patch.object(agents, "extract_source", side_effect=lose_file):
            with self.assertRaisesRegex(ValueError, "staged PDF is unavailable"):
                run_document_ingestion_preview(raw, draft)
        network.assert_not_called()

    def test_matching_draft_cannot_be_replaced_by_other_bytes(self):
        raw = pdf_bytes(pages=1)
        preview = {"page_count": 1, "source_sha256": sha256(raw).hexdigest(),
                   "source_file": "original.pdf"}
        with patch("phase2.agents.AgricultureDocumentsSourceAgent.execute") as execute:
            with self.assertRaisesRegex(ValueError, "does not match"):
                run_document_ingestion_preview(pdf_bytes(pages=2), preview)
        execute.assert_not_called()
