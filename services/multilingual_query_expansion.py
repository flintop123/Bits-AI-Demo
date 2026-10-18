"""Auditable bilingual vocabulary expansion for agriculture retrieval."""

import re


# These are domain concepts present in the indexed Bihar agriculture sources.
# Expansion is deliberately small and transparent; it complements rather than
# replaces multilingual embeddings.
CONCEPT_GROUPS = (
    ("organic", "जैविक", "ऑर्गेनिक"),
    ("corridor", "कॉरिडोर", "गलियारा"),
    ("Ganga", "गंगा"),
    ("district", "districts", "जिला", "जिले", "जिलों", "ज़िला"),
    ("agriculture", "farming", "कृषि", "खेती"),
    ("makhana", "fox nut", "fox nuts", "मखाना"),
    ("processing", "प्रसंस्करण"),
    ("export", "exports", "निर्यात"),
    ("scheme", "योजना"),
    ("handbook", "booklet", "पुस्तिका"),
    ("subsidy", "financial assistance", "सब्सिडी", "वित्तीय सहायता"),
    ("production", "उत्पादन"),
    ("yield", "उपज"),
    ("area", "क्षेत्रफल"),
)


def expand_document_query(*values, max_length=200):
    """Return de-duplicated source terms plus bilingual equivalents."""
    seeds = [re.sub(r"\s+", " ", str(value or "")).strip() for value in values]
    seeds = [value for value in seeds if value]
    if not seeds:
        return ""

    original = " ".join(seeds)
    lower = original.casefold()
    additions = []
    for group in CONCEPT_GROUPS:
        if not any(term.casefold() in lower for term in group):
            continue
        for term in group:
            if term.casefold() not in lower and term not in additions:
                additions.append(term)

    result = seeds[0]
    for term in additions:
        candidate = f"{result} {term}"
        if len(candidate) > max_length:
            break
        result = candidate
    return result
