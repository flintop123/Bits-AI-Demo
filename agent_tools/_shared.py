"""Small helpers shared by the @tool wrappers in this package.

Kept separate from agent_config.py because these are text-parsing helpers
for a single-string ReAct action input, not configuration.
"""

import re
import uuid

_WORD_TO_NUMBER = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30,
}


def new_run_id():
    """A fresh run id for provenance, matching the one Phase2Supervisor
    would generate for the same agent.execute() call."""
    return str(uuid.uuid4())


def wants_dry_run(instruction):
    """Heuristic: treat the free-text instruction as a dry run if it asks
    to validate/test rather than actually write data.

    This is fixed code, not a model decision — the LLM only decides *which*
    tool to call; whether that call writes to MongoDB is controlled by this
    explicit, auditable keyword check, not by the model's judgement.
    """
    text = str(instruction or "").lower()
    dry_run_markers = (
        "dry run", "dry-run", "validate", "without writing",
        "no write", "don't write", "do not write", "test only",
    )
    return any(marker in text for marker in dry_run_markers)


def extract_days(instruction, default=1):
    """Pull a day count out of free text like "load the last seven days of
    mandi data" or "pull 7 days of prices". Understands digits and the
    spelled-out numbers one through twenty, and thirty.

    This is fixed-code keyword/number parsing, not a model decision. A
    single-string ReAct action input is more reliable for a small local
    model than asking it to emit a structured {days: 7} argument, so the
    model's job stays "pick the right tool and pass along the request
    text" — the fixed code here does the actual parameter extraction.
    """
    text = str(instruction or "").lower()

    digit_match = re.search(r"(\d+)\s*day", text)
    if digit_match:
        return int(digit_match.group(1))

    for word, value in _WORD_TO_NUMBER.items():
        if re.search(rf"\b{word}\b\s*day", text):
            return value

    if "today" in text or "current" in text:
        return 1

    return default
