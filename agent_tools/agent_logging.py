"""Short, informational run log for the ReAct agent.

One line per step, written to the console and to logs/agent_run.log:

    Human input = "load mandi data via excel"
    Parsing human input and finding matching tool...
    Found required tool: ingest_crop_statistics | action: reading ...
    Agent reason: ...
    Tool result: status=completed; ...

Tools and the resolver log through ``get_logger()``, which stays silent
until ``configure_logging()`` attaches handlers (done by ``agent.run``), so
importing or unit-testing this package never creates log files.
"""

import logging
import sys
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

from agent_tools.capabilities import action_for_tool

LOGGER_NAME = "agent_tools.run"
DEFAULT_LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "agent_run.log"
_MAX_TEXT = 300


def get_logger():
    return logging.getLogger(LOGGER_NAME)


def configure_logging(log_file=DEFAULT_LOG_FILE):
    """Attach console and file handlers once; safe to call repeatedly."""
    logger = get_logger()
    if getattr(logger, "_agent_run_configured", False):
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Hindi text in log lines must not crash a cp1252 Windows console.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("[agent] %(message)s"))
    logger.addHandler(console)

    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(file_handler)
    logger._agent_run_configured = True
    return logger


def _short(value, limit=_MAX_TEXT):
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class AgentLogCallback(BaseCallbackHandler):
    """Logs the model's chosen action (and stated reason, if any), the tool
    being run, and its observation."""

    def __init__(self, logger=None):
        self.logger = logger or get_logger()

    def on_llm_end(self, response, **kwargs):
        try:
            message = response.generations[0][0].message
        except (AttributeError, IndexError):
            return
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            self.logger.info("Agent is composing the final answer")
            return
        content = message.content
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        reason = _short(content) if str(content).strip() else "(not stated)"
        for call in tool_calls:
            self.logger.info(
                "Agent reason: %s | chose tool=%s args=%s",
                reason, call.get("name"), _short(call.get("args"), 120),
            )

    def on_tool_start(self, serialized, input_str, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name")
        self.logger.info(
            "Performing action: %s (tool=%s)", action_for_tool(name), name
        )

    def on_tool_end(self, output, **kwargs):
        self.logger.info(
            "Tool result: %s", _short(getattr(output, "content", output))
        )

    def on_tool_error(self, error, **kwargs):
        self.logger.info("Tool failed: %s", _short(error))
