"""Background runner that drives the ReAct extractor for the browser.

One run at a time. The run executes on a worker thread, its agent log lines
are captured into a buffer the browser polls, and a clarification question
(unclear or ambiguous request) pauses the worker until the browser answers.
Importing this module is cheap: LangChain and the agent are imported only
when a run actually starts.
"""

import logging
import threading
import time
import uuid
from datetime import datetime, timezone

MAX_REQUEST_CHARS = 1000
MAX_LOG_LINES = 5000
CLARIFY_TIMEOUT_SECONDS = 600

ACTIVE = ("running", "waiting")
_UNSET = object()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunnerBusy(Exception):
    """A run is already in progress."""


class Run:
    def __init__(self, request, dry_run):
        self.id = uuid.uuid4().hex[:12]
        self.request = request
        self.dry_run = dry_run
        self.status = "running"
        self.answer = None
        self.error = None
        self.prompt = None
        self.overridden_input = None
        self.tool = None
        self.started_at = _now()
        self.finished_at = None
        self.history_saved = None
        self._final = None
        self._logs = []
        self._choice = _UNSET
        self._cond = threading.Condition()

    def log(self, text):
        with self._cond:
            if len(self._logs) == MAX_LOG_LINES:
                text = "(log truncated)"
            elif len(self._logs) > MAX_LOG_LINES:
                return
            self._logs.append({"time": time.strftime("%H:%M:%S"), "text": str(text)})

    def ask(self, message, options, timeout=CLARIFY_TIMEOUT_SECONDS):
        """Block the worker until the browser picks an option number (1-based)
        or cancels. Returns None on cancel or timeout."""
        with self._cond:
            self._choice = _UNSET
            self.prompt = {"message": message, "options": options}
            self.status = "waiting"
            self._cond.wait_for(lambda: self._choice is not _UNSET, timeout)
            choice = None if self._choice is _UNSET else self._choice
            self.prompt = None
            self.status = "running"
            return choice

    def answer_prompt(self, choice):
        """Deliver the browser's choice. Raises ValueError if invalid."""
        with self._cond:
            if self.prompt is None:
                raise LookupError("No question is waiting for an answer.")
            if choice is not None:
                count = len(self.prompt["options"])
                if (not isinstance(choice, int) or isinstance(choice, bool)
                        or not 1 <= choice <= count):
                    raise ValueError(f"choice must be 1 to {count}, or null to cancel.")
            self._choice = choice
            self._cond.notify_all()

    def finish(self, *, answer=None, error=None):
        """Record the outcome. The visible status stays 'running' until
        ``settle()``, so the browser never sees a finished run that has not
        yet been written to history."""
        with self._cond:
            self.answer = answer
            self.error = error
            self.finished_at = _now()
            self._final = "failed" if error else "completed"

    def settle(self):
        with self._cond:
            self.status = self._final or "completed"

    def document(self):
        """The MongoDB history record for this run."""
        with self._cond:
            return {
                "run_id": self.id,
                "human_input": self.request,
                "is_human_input_overridden": self.overridden_input is not None,
                "overridden_input": self.overridden_input,
                "dry_run": self.dry_run,
                "tool": self.tool,
                "status": self._final or self.status,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "logs": list(self._logs),
                "result": self.answer,
                "error": self.error,
            }

    def snapshot(self, after=0):
        with self._cond:
            after = max(0, after)
            return {
                "run_id": self.id,
                "request": self.request,
                "dry_run": self.dry_run,
                "status": self.status,
                "started_at": self.started_at,
                "history_saved": self.history_saved,
                "prompt": self.prompt,
                "answer": self.answer,
                "error": self.error,
                "logs": self._logs[after:],
                "next": len(self._logs),
            }


class _RunLogHandler(logging.Handler):
    def __init__(self, run):
        super().__init__(logging.INFO)
        self.run = run

    def emit(self, record):
        self.run.log(record.getMessage())


def _text(content):
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _force_dry_run(tool):
    """Copy of an ingestion tool whose instruction always asks for a dry run,
    so the checkbox holds even if the model rephrases the instruction."""
    from langchain_core.tools import StructuredTool

    original = tool.func

    def forced(instruction: str = "") -> str:
        return original(f"{instruction} dry run")

    return StructuredTool.from_function(
        forced, name=tool.name, description=tool.description,
    )


def agent_executor(run, request, dry_run, *, llm=None):
    """Run one request through the real resolver and ReAct agent."""
    import agent as agent_module
    from agent_tools.agent_logging import AgentLogCallback, configure_logging
    from agent_tools.capabilities import request_after_choice, resolve_request

    logger = configure_logging()
    handler = _RunLogHandler(run)
    logger.addHandler(handler)
    try:
        effective = f"{request} Dry run." if dry_run else request
        logger.info('Human input = "%s"', effective)

        shown = []

        def output_fn(text):
            shown.append(str(text))

        def input_fn(_prompt):
            options = [
                {"number": n, "label": cap.label}
                for n, cap in enumerate(resolve_request(effective).options, start=1)
            ]
            choice = run.ask(shown[-1] if shown else "Choose a source.", options)
            return "" if choice is None else str(choice)

        capability, user_chose = agent_module.resolve_capability(
            effective, logger=logger, interactive=True,
            input_fn=input_fn, output_fn=output_fn,
        )
        if capability is None:
            run.finish(answer="No tool was selected for this request.")
            return

        agent_request = (
            request_after_choice(capability, effective) if user_chose else effective
        )
        if user_chose:
            # The typed request was replaced by the option the user picked.
            run.overridden_input = agent_request
            logger.info('Request passed to agent = "%s"', agent_request)
        run.tool = capability.tool_name
        logger.info(
            "Found required tool: %s | action: %s",
            capability.tool_name, capability.action,
        )

        tool = {t.name: t for t in agent_module.default_tools()}[capability.tool_name]
        if dry_run and capability.domain != "question":
            tool = _force_dry_run(tool)
        agent = agent_module.build_agent(llm=llm, tools=[tool])

        final_state = None
        for state in agent.stream(
            {"messages": [{"role": "user", "content": agent_request}]},
            config={"callbacks": [AgentLogCallback(logger)]},
            stream_mode="values",
        ):
            final_state = state
        answer = _text(final_state["messages"][-1].content)
        logger.info("Final answer: %s", " ".join(answer.split())[:300])
        run.finish(answer=answer)
    finally:
        logger.removeHandler(handler)


class ExtractorRunner:
    def __init__(self, executor=None, history=None):
        self._executor = executor or agent_executor
        self.history = history
        self._lock = threading.Lock()
        self._runs = {}
        self._latest = None

    def start(self, request, dry_run):
        with self._lock:
            if self._latest is not None and self._latest.status in ACTIVE:
                raise RunnerBusy()
            run = Run(request, dry_run)
            self._runs[run.id] = run
            self._latest = run
        threading.Thread(target=self._work, args=(run,), daemon=True).start()
        return run

    def _work(self, run):
        try:
            self._executor(run, run.request, run.dry_run)
        except Exception as exc:  # noqa: BLE001 - reported to the browser
            run.log(f"Run failed: {exc}")
            run.finish(error=str(exc) or exc.__class__.__name__)
        if run._final is None:
            run.finish(answer=run.answer)
        if self.history is not None:
            try:
                self.history.save(run.document())
                run.history_saved = True
            except Exception as exc:  # noqa: BLE001 - never lose the result
                run.history_saved = False
                run.log(f"Could not save run history to MongoDB: {exc}")
        run.settle()

    def get(self, run_id):
        return self._runs.get(run_id)

    def latest(self):
        return self._latest