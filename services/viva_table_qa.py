"""Resolve narrow bilingual questions against the saved, verified PDF table cells."""

from decimal import Decimal, InvalidOperation
import re
import unicodedata


ROWS = {
    "wheat": ("गेहूँ", "गेहूं", "गेहू", "गेहुं", "गेहु"),
    "rice": ("धान", "चावल"),
    "maize": ("मक्का", "मकई", "corn"),
    "cash crop": ("cash crops", "नकदी फसल", "नकदी फसलें"),
    "cereals": ("cereal", "अनाज"),
    "oilseeds": ("oilseed", "तिलहन"),
    "pulses": ("pulse", "दलहन", "दालें"),
}
METRICS = {
    "area": ("cultivated area", "area under cultivation", "area", "क्षेत्रफल", "क्षेत्र", "रकबा"),
    "production": ("total production", "production", "produce", "produced", "output", "उत्पादन"),
    "yield": ("yield rate", "yield", "productivity", "उपज दर", "उपज", "उत्पादकता"),
    "outlay": ("outlay", "आवंटन", "परिव्यय"),
}
METRIC_LABELS = {
    "area": ("Area", "क्षेत्रफल"), "production": ("Production", "उत्पादन"),
    "yield": ("Yield", "उपज"), "outlay": ("Outlay", "परिव्यय"),
}
UNITS = {
    "mt": ("metric tonnes", "मीट्रिक टन"),
    "ha": ("hectares", "हेक्टेयर"),
    "hectare": ("hectares", "हेक्टेयर"),
    "kg ha": ("kg/ha", "कि.ग्रा./हेक्टेयर"),
    "kg hectare": ("kg/ha", "कि.ग्रा./हेक्टेयर"),
    "rs in lakh": ("lakh rupees", "लाख रुपये"),
}
WORD = re.compile(r"[\w\u0900-\u0963]+", re.UNICODE)
PERIOD = re.compile(r"(?<!\d)(20\d{2})\s*[-–—/]\s*(20\d{2}|\d{2})(?!\d)")
LANG_HINT = {
    "en": ("answer in english", "reply in english", "respond in english", "उत्तर अंग्रेजी में दें",
           "जवाब अंग्रेजी में दें", "अंग्रेजी में बताएं", "अंग्रेजी में बताइए"),
    "hi": ("answer in hindi", "reply in hindi", "respond in hindi", "उत्तर हिंदी में दें",
           "उत्तर हिन्दी में दें", "हिंदी में बताएं", "हिन्दी में बताएं", "हिंदी में बताइए"),
}
FILLER = set(("""
    what was were is are the of in for to how much many did does do it had has
    report reported from this pdf show give tell me please can you state provide
    recorded estimated estimate estimation figures value values total year years
    agricultural agriculture crop data under cultivation cultivated and
    का की के को ने में पर से लिए और कुल क्या कितना कितनी कितने था थी थे है हैं बताइए बताएँ बताएं
    बताओ दिखाएं दें बतायें कृपया इस रिपोर्ट दस्तावेज अनुसार वर्ष साल आंकड़े आँकड़े कृषि फसल
    फसलवार
""").split())
GEO = ("bihar", "बिहार")
FINAL = ("final", "अंतिम", "अन्तिम")
UNSUPPORTED = {
    "en": ("No unambiguous verified table answer in this PDF. Ask for one reviewed crop or row, "
           "a metric, and the report year if needed. Use Verified table cells to see what's covered."),
    "hi": ("इस PDF की सत्यापित तालिका से स्पष्ट उत्तर नहीं मिला। "
           "एक फसल या पंक्ति, उसका माप और ज़रूरत हो तो रिपोर्ट वर्ष बताएं।"),
}


def _digits(value):
    return "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in value)


def _clean(value):
    normalized = _digits(unicodedata.normalize("NFKC", value).casefold()).replace("़", "")
    return " ".join(WORD.findall(re.sub(r"(?<=\w)[’']s\b", "", normalized)))


def _has(text, phrase):
    return f" {phrase} " in f" {text} "


def _strip(text, phrases):
    for phrase in sorted(set(phrases), key=len, reverse=True):
        text = (" " + text + " ").replace(f" {phrase} ", " ").strip()
    return text


def _periods(text):
    return {f"{start}-{end[-2:]}" for start, end in PERIOD.findall(_digits(text))}


def _resolve_language(question, requested):
    clean = _clean(question)
    if requested != "auto":
        return requested
    for lang, phrases in LANG_HINT.items():
        if any(_has(clean, phrase) for phrase in phrases):
            return lang
    return "hi" if re.search(r"[\u0900-\u097f]", question) else "en"


def _display(value, lang, printed):
    if lang == "hi":
        return printed
    return f"{Decimal(value):,f}"


def answer_from_verified_tables(question, verified, answer_language):
    """Return an answer/refusal for table lookups; None for prose or unprofiled PDFs."""
    tables = verified.get("tables") or []
    if not tables:
        return None
    q = _clean(PERIOD.sub(" ", _digits(question)))
    wanted_periods = _periods(question)
    metrics = {name for name, aliases in METRICS.items() if any(_has(q, alias) for alias in aliases)}
    row_aliases = {
        _clean(cell["row"]): tuple({_clean(cell["row"]), *ROWS.get(_clean(cell["row"]), ())})
        for table in tables for cell in table["cells"]
    }
    row_names = {name for name, aliases in row_aliases.items() if any(_has(q, alias) for alias in aliases)}
    if not metrics:
        return None
    if not row_names and not wanted_periods and not any(
        _has(q, term) for term in ("how much", "how many", "कितना", "कितनी", "कितने")
    ):
        return None

    lang = _resolve_language(question, answer_language)
    refusal = {"status": "unsupported", "method": "verified_table", "answer_language": lang,
               "message": UNSUPPORTED[lang]}
    if len(row_names) != 1 or len(wanted_periods) > 1:
        return refusal
    row_name = next(iter(row_names))
    qualifiers = (*GEO, *FINAL, *LANG_HINT["en"], *LANG_HINT["hi"], "final estimate", "अंतिम अनुमान")
    remove = (*qualifiers, *row_aliases[row_name], *(a for m in metrics for a in METRICS[m]))
    if set(_strip(q, remove).split()) - FILLER:
        # Don't silently drop a district, variety, comparison, unit conversion or other restriction.
        return refusal

    require_bihar = any(_has(q, alias) for alias in GEO)
    require_final = any(_has(q, alias) for alias in FINAL)
    matches = {metric: [] for metric in metrics}
    for table_index, table in enumerate(tables):
        context = table.get("context", {})
        texts = {key: entry["text"] for key, entry in context.items()}
        geography = "Bihar" if _has(_clean(texts.get("geography", "")), "bihar") else ""
        final = _has(_clean(texts.get("estimate_stage", "")), "final")
        if (require_bihar and not geography) or (require_final and not final):
            continue
        for cell_index, cell in enumerate(table["cells"]):
            if _clean(cell["row"]) != row_name:
                continue
            column = _clean(cell["column"])
            metric = next((key for key in METRICS if column == key or column.startswith(key + " ")), None)
            if metric not in matches:
                continue
            periods = _periods(texts.get("period", "") or cell["column"])
            if len(periods) > 1 or (wanted_periods and wanted_periods != periods):
                continue
            anchor = cell.get("source_anchor", {})
            if anchor.get("kind") != "verified_table_cell" or not anchor.get("boxes"):
                continue
            try:
                value = Decimal(cell["value"])
            except (InvalidOperation, TypeError, ValueError):
                continue
            if not value.is_finite():
                continue
            matches[metric].append((table_index, cell_index, cell, next(iter(periods), ""), geography, final))
    if any(len(candidates) != 1 for candidates in matches.values()):
        return refusal
    selected = [(metric, candidates[0]) for metric, candidates in matches.items()]
    selected.sort(key=lambda item: item[1][:2])
    if len({item[1][3:] for item in selected}) != 1:
        return refusal

    language_index = int(lang == "hi")
    facts = []
    for metric, (table_index, cell_index, cell, period, geography, final) in selected:
        unit = UNITS.get(_clean(cell["unit"]), (cell["unit"], cell["unit"]))[language_index]
        facts.append({
            **{key: cell[key] for key in ("page_number", "row", "column", "value", "unit", "printed_text")},
            "table_index": table_index, "cell_index": cell_index,
            "label": METRIC_LABELS[metric][language_index], "display_unit": unit,
            "display_value": _display(cell["value"], lang, cell["printed_text"]),
        })
    first = facts[0]
    row_label = ROWS[row_name][0] if lang == "hi" and row_name in ROWS else first["row"]
    period_label = period.replace("-", "–")
    if lang == "en":
        scope = "Bihar" if geography else ""
        if period_label:
            scope = f"{scope}, {period_label}" if scope else period_label
        heading = f"{row_label} · {scope}" if scope else row_label
        message = "Answered from exact verified table cells."
    else:
        scope = "बिहार" if geography else ""
        if period_label:
            scope = f"{scope}, {period_label}" if scope else period_label
        heading = f"{row_label} · {scope}" if scope else row_label
        message = "उत्तर PDF की सत्यापित तालिका से लिया गया है।"
    return {
        "status": "answered", "method": "verified_table", "answer_language": lang, "message": message,
        "heading": heading, "estimate": ("अंतिम अनुमान" if lang == "hi" else "Final estimate") if final else "",
        "table_cells": facts,
    }
