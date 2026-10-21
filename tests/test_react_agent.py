"""Tests for the ReAct agent layer (agent.py, agent_tools/).

These intentionally avoid calling Ollama or MongoDB:

- AgentLoopTests script a fake chat model that returns structured tool
  calls, so the agent loop (model -> tool call -> tool result -> final
  answer) is verified without any live model or network call.
- test_*_tool_reports_errors_without_raising patch the underlying
  agent/orchestrator class (phase2.agents or phase4.mandi_orchestrator) to
  raise, and check the @tool wrapper returns an "ERROR: ..." string instead
  of propagating the exception, since an uncaught exception from inside a
  tool would otherwise crash the whole agent run during a live demo.
- ExtractDaysTests cover the fixed-code day-range parsing used by the mandi
  tool ("last seven days" -> 7), independent of any tool or model.

Running python agent.py "<request>" (or run_extractor.py) against real
Ollama/MongoDB is a separate, manual verification step — see
docs/REACT_AGENT.md.
"""

import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agent import build_agent


@tool
def echo_tool(text: str) -> str:
    """Echo back the given text. Used only by this test."""
    return f"echoed:{text}"


class ScriptedToolCallingModel(FakeMessagesListChatModel):
    """Returns scripted AIMessages. create_agent calls bind_tools() on the
    model, which the base fake model does not implement, so it returns self."""

    def bind_tools(self, tools, **kwargs):
        return self


class AgentLoopTests(unittest.TestCase):
    def test_tool_call_then_final_answer(self):
        fake_llm = ScriptedToolCallingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "echo_tool", "args": {"text": "hello"}, "id": "call_1"}
                    ],
                ),
                AIMessage(content="echoed:hello"),
            ]
        )
        agent = build_agent(llm=fake_llm, tools=[echo_tool])
        result = agent.invoke({"messages": [{"role": "user", "content": "echo hello"}]})
        self.assertEqual(result["messages"][-1].content, "echoed:hello")
        tool_messages = [m for m in result["messages"] if m.type == "tool"]
        self.assertEqual(tool_messages[0].content, "echoed:hello")

    def test_direct_answer_without_any_tool_call(self):
        fake_llm = ScriptedToolCallingModel(
            responses=[AIMessage(content="no tool was needed")]
        )
        agent = build_agent(llm=fake_llm, tools=[echo_tool])
        result = agent.invoke({"messages": [{"role": "user", "content": "anything"}]})
        self.assertEqual(result["messages"][-1].content, "no tool was needed")


class ToolErrorHandlingTests(unittest.TestCase):
    def test_mandi_tool_reports_errors_without_raising(self):
        from agent_tools.mandi_ingestion.tool import ingest_mandi_prices

        with patch(
            "agent_tools.mandi_ingestion.tool.DailyMandiOrchestrator"
        ) as mock_orchestrator_cls:
            mock_orchestrator_cls.return_value.run.side_effect = RuntimeError("boom")
            observation = ingest_mandi_prices.func("dry run")
        self.assertTrue(observation.startswith("ERROR:"))
        self.assertIn("boom", observation)

    def test_mandi_tool_passes_the_requested_day_count(self):
        from agent_tools.mandi_ingestion.tool import ingest_mandi_prices

        with patch(
            "agent_tools.mandi_ingestion.tool.DailyMandiOrchestrator"
        ) as mock_orchestrator_cls:
            mock_orchestrator_cls.return_value.run.return_value = {
                "status": "completed",
                "metrics": {
                    "dates_requested": 7,
                    "dates_completed": 7,
                    "records_processed": 100,
                    "inserted": 100,
                },
            }
            observation = ingest_mandi_prices.func(
                "load last seven days of mandi data via api, dry run"
            )
            called_dates = mock_orchestrator_cls.return_value.run.call_args[0][0]

        self.assertEqual(len(called_dates), 7)
        self.assertIn("dates_requested=7", observation)
        self.assertIn("dry_run=True", observation)

    def test_crop_statistics_tool_reports_errors_without_raising(self):
        from agent_tools.crop_statistics_ingestion.tool import (
            ingest_crop_statistics,
        )

        with patch(
            "agent_tools.crop_statistics_ingestion.tool.CropStatisticsSourceAgent"
        ) as mock_agent_cls:
            mock_agent_cls.return_value.execute.side_effect = RuntimeError("boom")
            observation = ingest_crop_statistics.func("dry run")
        self.assertTrue(observation.startswith("ERROR:"))

    def test_documents_tool_reports_errors_without_raising(self):
        from agent_tools.agriculture_documents_ingestion.tool import (
            ingest_agriculture_documents,
        )

        with patch(
            "agent_tools.agriculture_documents_ingestion.tool."
            "AgricultureDocumentsSourceAgent"
        ) as mock_agent_cls:
            mock_agent_cls.return_value.execute.side_effect = RuntimeError("boom")
            observation = ingest_agriculture_documents.func("dry run")
        self.assertTrue(observation.startswith("ERROR:"))

    def test_grounded_qa_tool_reports_errors_without_raising(self):
        from agent_tools.grounded_qa.tool import ask_agriculture_question

        with patch(
            "agent_tools.grounded_qa.tool.GroundedQAAgent"
        ) as mock_agent_cls:
            mock_agent_cls.return_value.execute.side_effect = RuntimeError("boom")
            observation = ask_agriculture_question.func("What was rice yield?")
        self.assertTrue(observation.startswith("ERROR:"))


class ToolMetadataTests(unittest.TestCase):
    def test_all_default_tools_have_names_and_descriptions(self):
        from agent import default_tools

        for a_tool in default_tools():
            self.assertTrue(a_tool.name)
            self.assertTrue(a_tool.description)


class ExtractDaysTests(unittest.TestCase):
    def test_spelled_out_number(self):
        from agent_tools._shared import extract_days

        self.assertEqual(
            extract_days("load last seven days of mandi data via api"), 7
        )

    def test_digit(self):
        from agent_tools._shared import extract_days

        self.assertEqual(extract_days("pull 14 days of prices"), 14)

    def test_today_keyword(self):
        from agent_tools._shared import extract_days

        self.assertEqual(extract_days("pull today's mandi prices"), 1)

    def test_default_when_nothing_mentioned(self):
        from agent_tools._shared import extract_days

        self.assertEqual(extract_days("pull mandi prices"), 1)

    def test_does_not_confuse_seventeen_with_seven(self):
        from agent_tools._shared import extract_days

        self.assertEqual(extract_days("load seventeen days of mandi data"), 17)


if __name__ == "__main__":
    unittest.main()
