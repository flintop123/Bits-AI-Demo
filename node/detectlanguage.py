def detect_script_unicode(text: str) -> str:
    devanagari_count = 0
    latin_count = 0

    for char in text:
        # Check Devanagari Unicode range
        if "\u0900" <= char <= "\u097f":
            devanagari_count += 1
        # Check Basic Latin (English alphabet)
        elif "a" <= char.lower() <= "z":
            latin_count += 1

    if devanagari_count > latin_count:
        return "Hindi (Devanagari)"
    elif latin_count > devanagari_count:
        return "English"
    else:
        return "Unknown / Neutral"