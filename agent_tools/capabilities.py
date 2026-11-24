"""Capability table and request resolver for the ReAct agent.

The table below is the single, in-code list of what the agent can actually
do: each entry is a (domain, source format) pair mapped to one @tool. The
resolver reads a free-text request and decides, in fixed code and before any
model is involved, which capability it means. If the request is ambiguous,
names a combination that does not exist (for example "mandi data via
excel"), or cannot be classified, the resolver says so and ``clarify()``
shows the valid options and asks the user to pick one, instead of letting a
small local model guess.

Nothing here imports langchain or touches MongoDB, so it is cheap to import
and to test.
"""

import re
from dataclasses import dataclass, field

INGEST = "ingest"
QUESTION = "question"


@dataclass(frozen=True)
class Capability:
    key: str
    domain: str
    source_format: str
    tool_name: str
    label: str
    action: str
    domain_keywords: tuple = ()


CAPABILITIES = (
    Capability(
        key="mandi_api",
        domain="mandi",
        source_format="api",
        tool_name="ingest_mandi_prices",
        label="Mandi prices from the official Bihar API",
        action="fetching mandi prices from the official API",
        domain_keywords=("mandi", "market price", "मंडी"),
    ),
    Capability(
        key="crop_statistics_excel",
        domain="crop_statistics",
        source_format="excel",
        tool_name="ingest_crop_statistics",
        label="Crop area / production / yield from the Excel workbook",
        action="reading crop statistics from the Excel workbook",
        domain_keywords=(
            "crop statistic", "crop stat", "crop-wise", "crop wise",
            "crop area", "area production", "production", "yield", "फसल",
        ),
    ),
    Capability(
        key="documents_pdf",
        domain="documents",
        source_format="pdf",
        tool_name="ingest_agriculture_documents",
        label="Agriculture PDFs, English or Hindi (OCR for scans)",
        action="extracting text from agriculture PDFs (OCR where needed)",
        domain_keywords=(
            "document", "scheme", "policy", "brochure", "handbook",
            "makhana", "apeda", "pmfme", "horticulture", "मखाना",
            "दस्तावेज", "योजना",
        ),
    ),
    Capability(
        key="grounded_qa",
        domain="question",
        source_format="database",
        tool_name="ask_agriculture_question",
        label="Answer a question from data already stored",
        action="searching stored data to answer the question",
    ),
)

_BY_TOOL = {cap.tool_name: cap for cap in CAPABILITIES}
_INGESTION = tuple(cap for cap in CAPABILITIES if cap.domain != "question")
_QA = _BY_TOOL["ask_agriculture_question"]

# Words that name a source format explicitly. "pdf" is a format word only,
# so "mandi pdf" is reported as unsupported instead of being read as a
# documents request.
FORMAT_KEYWORDS = {
    "api": ("api",),
    "excel": ("excel", "xlsx", "xls", "workbook", "spreadsheet"),
    "pdf": ("pdf",),
}

_INGEST_VERBS = (
    "load", "fetch", "ingest", "pull", "update", "refresh", "download",
    "index", "extract", "import", "scrape", "sync",
)
_QUESTION_STARTS = (
    "what", "which", "how", "why", "when", "who", "where", "is", "are",
    "was", "were", "does", "did", "compare", "show", "list", "trace", "find",
    "क्या", "कितना", "कितनी", "कौन",
)
_HINDI_QUERY_ENDINGS = ("दिखाएँ", "दिखाएं", "दिखाइए", "बताएँ", "बताएं", "बताइए")


def capability_for_tool(tool_name):
    return _BY_TOOL.get(tool_name)


def action_for_tool(tool_name):
    capability = _BY_TOOL.get(tool_name)
    return capability.action if capability else "running the selected tool"


@dataclass
class Resolution:
    status: str  # resolved | ambiguous | unsupported | unclear
    reason: str
    capability: Capability = None
    options: tuple = field(default_factory=tuple)


def _contains(text, keyword):
    if keyword.isascii():
        return re.search(rf"\b{re.escape(keyword)}", text) is not None
    return keyword in text


def _detect_intent(text):
    words = text.split()
    first_word = words[0].strip(".,!?।") if words else ""
    if first_word in _QUESTION_STARTS:
        return QUESTION
    if words and words[-1].rstrip(".,!?।") in _HINDI_QUERY_ENDINGS:
        return QUESTION
    if any(re.search(rf"\b{verb}\b", text) for verb in _INGEST_VERBS):
        return INGEST
    if "?" in text:
        return QUESTION
    return None


def _detect_formats(text):
    return [
        name for name, words in FORMAT_KEYWORDS.items()
        if any(_contains(text, word) for word in words)
    ]


def resolve_request(request):
    """Map a free-text request to one capability, or say why it can't."""
    text = str(request or "").lower()
    intent = _detect_intent(text)

    if intent == QUESTION:
        return Resolution(
            "resolved", "request reads as a question about stored data", _QA
        )
    if intent is None:
        return Resolution(
            "unclear",
            "could not tell whether this is a data load or a question",
            options=CAPABILITIES,
        )

    domains = [
        cap for cap in _INGESTION
        if any(_contains(text, kw) for kw in cap.domain_keywords)
    ]
    formats = _detect_formats(text)

    if domains and formats:
        matches = [cap for cap in domains if cap.source_format in formats]
        if len(matches) == 1:
            cap = matches[0]
            return Resolution(
                "resolved",
                f"request names {cap.domain} data and {cap.source_format}",
                cap,
            )
        if not matches:
            wanted = "/".join(formats)
            names = ", ".join(cap.domain for cap in domains)
            return Resolution(
                "unsupported",
                f"{names} data is not available as {wanted}",
                options=_INGESTION,
            )
        return Resolution(
            "ambiguous", "request matches more than one source",
            options=tuple(matches),
        )

    if formats:
        matches = [cap for cap in _INGESTION if cap.source_format in formats]
        if len(matches) == 1:
            cap = matches[0]
            return Resolution(
                "resolved", f"request names the {cap.source_format} format", cap
            )
        return Resolution(
            "unclear", f"no source supports {'/'.join(formats)}",
            options=_INGESTION,
        )

    if len(domains) == 1:
        cap = domains[0]
        return Resolution(
            "resolved", f"request mentions {cap.domain} data", cap
        )
    if domains:
        return Resolution(
            "ambiguous", "request matches more than one data domain",
            options=tuple(domains),
        )
    return Resolution(
        "unclear", "request does not name a known data source",
        options=_INGESTION,
    )


def request_after_choice(capability, original):
    """The request text to hand the model after the user picked an option.

    The original text may describe a combination that doesn't exist ("load
    mandi data via excel"); passing it on unchanged makes the model refuse
    even though the user has already chosen a valid source. So the request
    is restated from the chosen capability, keeping only the modifiers that
    fixed code can read from the original: a day count and dry run. Questions
    are passed through untouched.
    """
    from agent_tools._shared import extract_days, wants_dry_run

    if capability.domain == "question":
        return original
    parts = [f"Load: {capability.label}."]
    days = extract_days(original, default=None)
    if capability.domain == "mandi" and days:
        parts.append(f"Period: last {days} day(s).")
    if wants_dry_run(original):
        parts.append("Dry run.")
    return " ".join(parts)


def describe(resolution):
    """Human-readable explanation plus the numbered list of valid options."""
    headers = {
        "unsupported": "That combination is not supported",
        "ambiguous": "The request matches more than one source",
        "unclear": "I could not tell which source you mean",
    }
    lines = [f"{headers.get(resolution.status, 'Clarification needed')}: "
             f"{resolution.reason}.", "Available options:"]
    for number, cap in enumerate(resolution.options, start=1):
        lines.append(f"  {number}) {cap.label}")
    return "\n".join(lines)


def clarify(resolution, *, input_fn=input, output_fn=print, max_attempts=3):
    """Show the options and return the Capability the user picks, or None
    if they cancel, run out of attempts, or input is unavailable."""
    output_fn(describe(resolution))
    options = resolution.options
    for _ in range(max_attempts):
        try:
            raw = input_fn("Choose an option number (Enter to cancel): ")
        except EOFError:
            return None
        raw = str(raw).strip()
        if not raw:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        output_fn(f"Please enter a number from 1 to {len(options)}.")
    return None
