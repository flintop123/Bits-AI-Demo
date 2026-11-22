"""Second-level selection: which manifest PDFs does a request mean?

Pure fixed code over the manifest entries (``sources/agriculture_sources.yaml``).
The model never picks source ids or URLs; it only passes the request text,
and this module narrows the allowlisted manifest from it.
"""

_LANGUAGE_WORDS = {
    "hi": ("hindi", "हिंदी", "हिन्दी"),
    "en": ("english", "अंग्रेजी", "अंग्रेज़ी"),
}


def _requested_language(text):
    found = {
        code for code, words in _LANGUAGE_WORDS.items()
        if any(word in text for word in words)
    }
    return found.pop() if len(found) == 1 else None


def select_pdf_sources(instruction, sources):
    """Return (selected_sources, reason).

    Order of precedence: an exact source id in the text; then keyword hits
    from each source's optional ``keywords`` list; then a Hindi/English
    language filter ("mixed" documents satisfy either); otherwise every
    enabled source, matching the previous default behaviour.
    """
    text = str(instruction or "").lower()
    enabled = [source for source in sources if source["enabled"]]

    id_hits = [source for source in enabled if source["id"].lower() in text]
    if id_hits:
        return id_hits, "request names the source id"

    keyword_hits = [
        source for source in enabled
        if any(str(kw).lower() in text for kw in source.get("keywords") or ())
    ]
    pool = keyword_hits or enabled
    reasons = ["request keywords matched" if keyword_hits else "no specific PDF named"]

    language = _requested_language(text)
    if language:
        pool = [s for s in pool if s["language"] in (language, "mixed")]
        reasons.append(f"filtered to {language} (and mixed) documents")

    return pool, "; ".join(reasons)
