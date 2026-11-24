"""Conservative section evidence from numbered headings in extracted PDF text."""

import re


_HEADING = re.compile(r"^[ \t]*(?:\d{1,2}\.){1,6}\d{1,2}\.?[ \t]+([^\r\n]+)", re.MULTILINE)


def numbered_headings(text):
    """Yield literal heading lines and their offsets in one normalized PDF chunk."""
    for match in _HEADING.finditer(text):
        line = match.group().strip()
        title = match.group(1).strip()
        if (
            3 <= len(title) <= 130 and title[0].isalpha() and not title[0].islower()
            and not title.endswith((".", ";", "?"))
        ):
            yield (match.start(), match.end(), line)


def leading_heading(text):
    headings = list(numbered_headings(text))
    if len(headings) == 1 and not text[:headings[0][0]].strip():
        return headings[0][2]
    return None


def heading_for_evidence(text, start, end):
    if start is None or end is None or not 0 <= start < end <= len(text):
        return None
    if any(start < position < end for position, _, _ in numbered_headings(text)):
        return None
    eligible = [heading for position, _, heading in numbered_headings(text) if position <= start]
    return eligible[-1] if eligible else None
