"""Tests for the pre-agent resolution layer: capability table, resolver,
clarification prompt, PDF source selection and the run log.

No Ollama, MongoDB or network access is needed.
"""

import logging
import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage

from agent_tools.agriculture_documents_ingestion.selection import (
    select_pdf_sources,
)
from agent_tools.capabilities import (
    CAPABILITIES,
    capability_for_tool,
    clarify,
    describe,
    resolve_request,
)


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class CapabilityTableTests(unittest.TestCase):
    def test_every_capability_maps_to_a_real_tool(self):
        from agent import default_tools

        tool_names = {t.name for t in default_tools()}
        for capability in CAPABILITIES:
            self.assertIn(capability.tool_name, tool_names)
        self.assertEqual(len(CAPABILITIES), len(tool_names))

    def test_lookup_by_tool_name(self):
        self.assertEqual(
            capability_for_tool("ingest_mandi_prices").source_format, "api"
        )


class ResolverTests(unittest.TestCase):
    def assertResolves(self, request, tool_name):
        resolution = resolve_request(request)
        self.assertEqual(resolution.status, "resolved", resolution.reason)
        self.assertEqual(resolution.capability.tool_name, tool_name)

    def test_mandi_via_api(self):
        self.assertResolves(
            "load last seven days of mandi data via api", "ingest_mandi_prices"
        )

    def test_mandi_alone_defaults_to_the_only_mandi_source(self):
        self.assertResolves("pull today's mandi prices", "ingest_mandi_prices")

    def test_crop_statistics_excel(self):
        self.assertResolves(
            "load crop statistics from excel", "ingest_crop_statistics"
        )

    def test_excel_alone_means_crop_workbook(self):
        self.assertResolves("load the excel file", "ingest_crop_statistics")

    def test_hindi_pdfs(self):
        self.assertResolves("ingest hindi makhana pdfs", "ingest_agriculture_documents")

    def test_question(self):
        self.assertResolves(
            "what was total rice production in 2024-25?",
            "ask_agriculture_question",
        )

    def test_mandi_via_excel_is_unsupported_and_offers_options(self):
        resolution = resolve_request("load mandi data via excel")
        self.assertEqual(resolution.status, "unsupported")
        self.assertIn("mandi", resolution.reason)
        self.assertIn("excel", resolution.reason)
        tools = {cap.tool_name for cap in resolution.options}
        self.assertIn("ingest_mandi_prices", tools)
        self.assertIn("ingest_crop_statistics", tools)
        self.assertNotIn("ask_agriculture_question", tools)

    def test_mandi_pdf_is_unsupported(self):
        self.assertEqual(resolve_request("load mandi pdf").status, "unsupported")

    def test_two_domains_is_ambiguous(self):
        resolution = resolve_request("load mandi crop production data")
        self.assertEqual(resolution.status, "ambiguous")
        self.assertEqual(len(resolution.options), 2)

    def test_unrecognised_request_is_unclear(self):
        self.assertEqual(resolve_request("hello there").status, "unclear")
        self.assertEqual(resolve_request("load some data").status, "unclear")


class ClarifyTests(unittest.TestCase):
    def test_valid_choice_returns_that_capability(self):
        resolution = resolve_request("load mandi data via excel")
        out = []
        chosen = clarify(
            resolution, input_fn=lambda _: "1", output_fn=out.append
        )
        self.assertEqual(chosen, resolution.options[0])
        self.assertIn("not supported", out[0])

    def test_invalid_then_valid_choice(self):
        resolution = resolve_request("load mandi data via excel")
        answers = iter(["9", "abc", "2"])
        chosen = clarify(
            resolution, input_fn=lambda _: next(answers), output_fn=lambda _: None
        )
        self.assertEqual(chosen, resolution.options[1])

    def test_empty_input_cancels(self):
        resolution = resolve_request("load mandi data via excel")
        self.assertIsNone(
            clarify(resolution, input_fn=lambda _: "", output_fn=lambda _: None)
        )

    def test_eof_cancels(self):
        resolution = resolve_request("load mandi data via excel")

        def raise_eof(_):
            raise EOFError

        self.assertIsNone(
            clarify(resolution, input_fn=raise_eof, output_fn=lambda _: None)
        )

    def test_describe_lists_numbered_options(self):
        text = describe(resolve_request("load mandi data via excel"))
        self.assertIn("1)", text)
        self.assertIn("Available options", text)


MANIFEST = [
    {"id": "scheme_en", "language": "en", "enabled": True,
     "keywords": ["scheme"]},
    {"id": "brochure_mixed", "language": "mixed", "enabled": True,
     "keywords": ["brochure"]},
    {"id": "makhana_hi", "language": "hi", "enabled": True,
     "keywords": ["makhana", "मखाना"]},
    {"id": "off_hi", "language": "hi", "enabled": False, "keywords": ["off"]},
]


def ids(selected):
    return [source["id"] for source in selected]


class PdfSelectionTests(unittest.TestCase):
    def test_no_hint_selects_all_enabled(self):
        selected, _ = select_pdf_sources("ingest pdfs", MANIFEST)
        self.assertEqual(ids(selected), ["scheme_en", "brochure_mixed", "makhana_hi"])

    def test_keyword_selects_matching_source(self):
        selected, _ = select_pdf_sources("load the makhana report", MANIFEST)
        self.assertEqual(ids(selected), ["makhana_hi"])

    def test_hindi_keyword(self):
        selected, _ = select_pdf_sources("मखाना pdf ingest", MANIFEST)
        self.assertEqual(ids(selected), ["makhana_hi"])

    def test_language_filter_keeps_mixed(self):
        selected, _ = select_pdf_sources("ingest hindi pdfs", MANIFEST)
        self.assertEqual(ids(selected), ["brochure_mixed", "makhana_hi"])

    def test_english_filter(self):
        selected, _ = select_pdf_sources("ingest english pdfs", MANIFEST)
        self.assertEqual(ids(selected), ["scheme_en", "brochure_mixed"])

    def test_source_id_wins(self):
        selected, _ = select_pdf_sources("ingest scheme_en only", MANIFEST)
        self.assertEqual(ids(selected), ["scheme_en"])

    def test_keyword_and_conflicting_language_selects_nothing(self):
        selected, _ = select_pdf_sources("english makhana pdf", MANIFEST)
        self.assertEqual(selected, [])

    def test_disabled_sources_are_never_selected(self):
        selected, _ = select_pdf_sources("off", MANIFEST)
        self.assertNotIn("off_hi", ids(selected))


class DocumentsToolSelectionTests(unittest.TestCase):
    def test_tool_passes_only_the_selected_sources_to_the_agent(self):
        from agent_tools.agriculture_documents_ingestion.tool import (
            ingest_agriculture_documents,
        )

        with patch(
            "agent_tools.agriculture_documents_ingestion.tool."
            "AgricultureDocumentsSourceAgent"
        ) as agent_cls:
            agent_cls.return_value.execute.return_value.status = "completed"
            agent_cls.return_value.execute.return_value.summary = {}
            observation = ingest_agriculture_documents.func(
                "dry run apeda report"
            )
        self.assertEqual(
            agent_cls.call_args.kwargs["source_ids"], ["apeda_makhana_hindi"]
        )
        self.assertIn("selected=apeda_makhana_hindi", observation)

    def test_tool_reports_when_nothing_matches(self):
        from agent_tools.agriculture_documents_ingestion.tool import (
            ingest_agriculture_documents,
        )

        observation = ingest_agriculture_documents.func(
            "english makhana pdf dry run"
        )
        self.assertTrue(observation.startswith("ERROR:"))
        self.assertIn("Available sources", observation)


class RunFlowTests(unittest.TestCase):
    def test_unsupported_request_is_not_run_when_non_interactive(self):
        import agent

        out = []
        logger = logging.getLogger("agent_tools.run")
        with patch.object(agent, "configure_logging", return_value=logger):
            with patch.object(agent, "build_agent") as build:
                result = agent.run(
                    "load mandi data via excel",
                    interactive=False,
                    output_fn=out.append,
                )
        build.assert_not_called()
        self.assertEqual(result, "No tool was selected for this request.")
        self.assertIn("not supported", out[0])

    def test_user_choice_restricts_agent_to_that_tool_and_logs_steps(self):
        import agent

        fake_llm = ScriptedModel(
            responses=[
                AIMessage(
                    content="Request is about crop data in Excel.",
                    tool_calls=[{
                        "name": "ingest_crop_statistics",
                        "args": {"instruction": "dry run"},
                        "id": "call_1",
                    }],
                ),
                AIMessage(content="done"),
            ]
        )
        logger = logging.getLogger("agent_tools.run")
        with patch.object(agent, "configure_logging", return_value=logger), \
                patch(
                    "agent_tools.crop_statistics_ingestion.tool."
                    "CropStatisticsSourceAgent"
                ) as crop_cls, \
                self.assertLogs("agent_tools.run", level="INFO") as logs:
            crop_cls.return_value.execute.return_value.status = "completed"
            crop_cls.return_value.execute.return_value.summary = {}
            answer = agent.run(
                "load mandi data via excel",
                verbose=False,
                llm=fake_llm,
                interactive=True,
                input_fn=lambda _: "2",
                output_fn=lambda _: None,
            )
        self.assertEqual(answer, "done")
        text = "\n".join(logs.output)
        self.assertIn('Human input = "load mandi data via excel"', text)
        self.assertIn("Parsing human input and finding matching tool", text)
        self.assertIn("Found required tool: ingest_crop_statistics", text)
        self.assertIn("Agent reason: Request is about crop data in Excel.", text)
        self.assertIn("Performing action: reading crop statistics", text)
        self.assertIn("Tool result:", text)


class RequestAfterChoiceTests(unittest.TestCase):
    def test_restated_request_drops_the_conflicting_original_wording(self):
        from agent_tools.capabilities import request_after_choice

        crop = capability_for_tool("ingest_crop_statistics")
        text = request_after_choice(crop, "load mandi data via excel")
        self.assertIn(crop.label, text)
        self.assertNotIn("mandi", text.lower())

    def test_keeps_days_and_dry_run(self):
        from agent_tools.capabilities import request_after_choice

        mandi = capability_for_tool("ingest_mandi_prices")
        text = request_after_choice(
            mandi, "load last seven days of mandi data via excel, dry run"
        )
        self.assertIn("last 7 day(s)", text)
        self.assertIn("Dry run", text)

    def test_question_is_passed_through(self):
        from agent_tools.capabilities import request_after_choice

        qa = capability_for_tool("ask_agriculture_question")
        self.assertEqual(request_after_choice(qa, "rice yield?"), "rice yield?")

    def test_run_sends_the_restated_request_to_the_model(self):
        import agent

        fake_llm = ScriptedModel(responses=[AIMessage(content="ok")])
        logger = logging.getLogger("agent_tools.run")
        with patch.object(agent, "configure_logging", return_value=logger), \
                self.assertLogs("agent_tools.run", level="INFO") as logs:
            agent.run(
                "load mandi data via excel", verbose=False, llm=fake_llm,
                interactive=True, input_fn=lambda _: "2",
                output_fn=lambda _: None,
            )
        sent = [line for line in logs.output if "Request passed to agent" in line]
        self.assertEqual(len(sent), 1)
        self.assertIn("Excel workbook", sent[0])
        self.assertNotIn("mandi", sent[0].lower())


class ParseCliTests(unittest.TestCase):
    def test_non_interactive_flag_is_stripped(self):
        from agent import parse_cli

        self.assertEqual(
            parse_cli(["--non-interactive", "load", "mandi"]),
            ("load mandi", False),
        )
        self.assertEqual(parse_cli(["load", "mandi"]), ("load mandi", None))


if __name__ == "__main__":
    unittest.main()
