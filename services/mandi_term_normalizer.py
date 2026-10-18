"""Safe bilingual normalization for structured mandi filters."""

import re
import unicodedata
from pathlib import Path

import yaml

from services.local_translation_service import (
    LocalTranslationError,
    LocalTranslationService,
)


CROP_GROUPS = (
    ("आलू", "potato", "potatoes", "aloo"),
    ("प्याज", "onion", "onions", "pyaz", "pyaaz"),
    ("बैंगन", "brinjal", "eggplant", "aubergine", "baingan"),
    ("टमाटर", "tomato", "tomatoes", "tamatar"),
    ("मक्का", "maize", "corn", "makka"),
    ("धान", "paddy", "rice paddy", "dhan"),
    ("गेहूं", "गेहूँ", "wheat", "gehun", "gehu"),
    ("फूलगोभी", "cauliflower", "phool gobhi"),
    ("पत्तागोभी", "cabbage", "patta gobhi"),
    ("लौकी", "bottle gourd", "lauki"),
    ("खीरा", "cucumber", "khira"),
    ("भिंडी", "okra", "lady finger", "bhindi"),
    ("हरी मिर्च", "green chilli", "green chili", "chilli", "chili"),
    ("लहसुन", "garlic", "lahsun"),
    ("अदरक(हरा)", "अदरक", "ginger", "green ginger", "adrak"),
    ("चना", "chickpea", "gram", "bengal gram", "chana"),
    ("मसूर", "lentil", "lentils", "masur"),
    ("सरसों", "mustard", "sarson"),
    ("केला", "banana", "bananas", "kela"),
    ("आम", "mango", "mangoes", "aam"),
    ("अमरूद", "guava", "amrud"),
    ("मखाना", "makhana", "fox nut", "fox nuts"),
)

DISTRICT_GROUPS = (
    ("अररिया", "Araria"), ("अरवल", "Arwal"),
    ("औरंगाबाद", "Aurangabad"), ("कटिहार", "Katihar"),
    ("किशनगंज", "Kishanganj"), ("कैमूर", "Kaimur", "Bhabua"),
    ("खगड़िया", "खगरिया", "Khagaria"), ("गया", "Gaya"),
    ("गोपालगंज", "Gopalganj"), ("जमुई", "Jamui"),
    ("जहानाबाद", "Jehanabad"), ("दरभंगा", "Darbhanga"),
    ("नवादा", "Nawada"), ("नालन्दा", "नालंदा", "Nalanda"),
    ("पटना", "Patna"), ("पूर्णिया", "Purnia", "Purnea"),
    ("पूर्वी चंपारण", "East Champaran", "Purbi Champaran"),
    ("पश्चिम चंपारण", "West Champaran", "Pashchim Champaran"),
    ("बक्सर", "Buxar"), ("बांका", "Banka"),
    ("बेगूसराय", "Begusarai"), ("भागलपुर", "Bhagalpur"),
    ("भोजपुर", "Bhojpur"), ("मधेपुरा", "Madhepura"),
    ("मधुबनी", "Madhubani"), ("मुंगेर", "Munger"),
    ("मुजफ्फरपुर", "Muzaffarpur"), ("रोहतास", "Rohtas"),
    ("लखीसराय", "Lakhisarai"), ("वैशाली", "Vaishali"),
    ("शेखपुरा", "Sheikhpura"), ("शिवहर", "Sheohar"),
    ("सहरसा", "Saharsa"), ("समस्तीपुर", "Samastipur"),
    ("सारण", "Saran", "Chapra"), ("सीतामढ़ी", "Sitamarhi"),
    ("सीवान", "Siwan"), ("सुपौल", "Supaul"),
)

# Reviewed display aliases for official market values that are published in
# Latin script. These remain presentation metadata: the official database
# value is still used for filtering and identity.
MARKET_LABEL_GROUPS = (
    ("Samastipur APMC", "समस्तीपुर एपीएमसी"),
)


def _normal(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = re.sub(r"[\s_-]+", " ", value).strip().casefold()
    return value


class MandiTermNormalizer:
    """Resolve bilingual input only to values present in the live catalog."""

    def __init__(self, translator=None, market_alias_path=None):
        self.translator = translator
        self.market_alias_path = Path(
            market_alias_path or "sources/mandi_market_aliases.yaml"
        )
        self._market_groups = None

    def resolve_filters(self, filters, catalog):
        resolved = {}
        evidence = {}
        choices_by_field = {
            "crop": catalog.get("mandi_crops", []),
            "district": catalog.get("districts", []),
            "market": catalog.get("markets", []),
            "variety": catalog.get("mandi_varieties", []),
        }
        for field, value in filters.items():
            if field not in choices_by_field or not str(value or "").strip():
                resolved[field] = value
                continue
            result, method, translated = self.resolve(
                value, choices_by_field[field], field
            )
            resolved[field] = result
            evidence[field] = {
                "requested": str(value).strip(),
                "resolved": result,
                "method": method,
            }
            if translated:
                evidence[field]["translated_candidate"] = translated
        return resolved, evidence

    def localized_options(self, values, field, language):
        """Build labels for live catalog values without inventing options."""
        language = str(language or "").lower()
        if language not in {"en", "hi"}:
            raise ValueError("catalog language must be en or hi")
        official_values = sorted({
            str(value).strip() for value in values if str(value or "").strip()
        })
        groups = {
            "crop": CROP_GROUPS,
            "district": DISTRICT_GROUPS,
            "market": self._market_alias_groups(),
        }.get(field, ())
        entries = []
        pending = []

        for value in official_values:
            source_language = self._language(value)
            if source_language == language:
                entries.append(self._option(
                    value, value, language, "official_catalog_label"
                ))
                continue
            alias = self._group_label(value, groups, language)
            if alias:
                entries.append(self._option(
                    value, alias, language, "reviewed_bilingual_alias"
                ))
                continue
            if field == "market":
                if source_language == "hi" and language == "en":
                    label = self._transliterate_market_name(value)
                    entries.append(self._option(
                        value, label, "en", "devanagari_transliteration"
                    ))
                else:
                    # Place names must never be sent through an unconstrained
                    # semantic translation model. Retaining the official name
                    # is safer than inventing a different locality.
                    entries.append(self._option(
                        value, value, source_language,
                        "official_place_name_translation_unavailable",
                    ))
                continue
            pending.append((value, source_language))

        for source_language in {item[1] for item in pending}:
            source_values = [
                item[0] for item in pending if item[1] == source_language
            ]
            translations = self._translate_catalog_values(
                source_values, source_language, language
            )
            for value, translated in zip(source_values, translations):
                if translated:
                    entries.append(self._option(
                        value, translated, language, "offline_translation"
                    ))
                else:
                    entries.append(self._option(
                        value, value, source_language,
                        "official_label_translation_unavailable",
                    ))

        return sorted(
            entries,
            key=lambda item: (_normal(item["label"]), _normal(item["value"])),
        )

    @staticmethod
    def _transliterate_market_name(value):
        """Romanize a Devanagari place name without semantic generation."""
        value = unicodedata.normalize("NFKC", str(value or "")).strip()
        value = re.sub(
            r"\s*\((?:नया|नई|पुराना|पुरानी)\)\s*", " ", value
        )
        value = re.sub(r"\s+मंडी\s*", " ", value).strip()
        independent_vowels = {
            "अ": "a", "आ": "a", "इ": "i", "ई": "i",
            "उ": "u", "ऊ": "u", "ऋ": "ri", "ए": "e",
            "ऐ": "ai", "ओ": "o", "औ": "au",
        }
        consonants = {
            "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
            "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
            "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
            "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
            "प": "p", "फ": "f", "ब": "b", "भ": "bh", "म": "m",
            "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
            "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh",
            "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
        }
        vowel_signs = {
            "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
            "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
        }
        output = []
        index = 0
        while index < len(value):
            character = value[index]
            if character in consonants:
                syllable = consonants[character]
                following = value[index + 1] if index + 1 < len(value) else ""
                if following in vowel_signs:
                    syllable += vowel_signs[following]
                    index += 1
                elif following == "्":
                    index += 1
                else:
                    syllable += "a"
                output.append(syllable)
            elif character in independent_vowels:
                output.append(independent_vowels[character])
            elif character in {"ं", "ँ"}:
                output.append("n")
            elif character == "ः":
                output.append("h")
            elif character == "़":
                pass
            else:
                output.append(character)
            index += 1

        romanized = re.sub(r"\s+", " ", "".join(output)).strip()
        words = []
        for word in romanized.split(" "):
            word = re.sub(r"a(?=[),.-]?$)", "", word)
            words.append(word[:1].upper() + word[1:] if word else word)
        return " ".join(words) or value

    def _translate_catalog_values(
        self, values, source_language, target_language
    ):
        if not values:
            return []
        translator = self.translator
        if translator is None:
            translator = LocalTranslationService()
            self.translator = translator
        try:
            if hasattr(translator, "translate_many"):
                return translator.translate_many(
                    values, source_language, target_language
                )
            return [
                translator.translate(
                    value, source_language, target_language
                )
                for value in values
            ]
        except (LocalTranslationError, OSError, ValueError):
            return [None] * len(values)

    @classmethod
    def _group_label(cls, value, groups, language):
        normalized = _normal(value)
        for group in groups:
            if normalized not in {_normal(item) for item in group}:
                continue
            for item in group:
                if cls._language(item) == language:
                    return cls._display_case(item, language)
        return None

    @staticmethod
    def _option(value, label, language, method):
        return {
            "value": value,
            "label": MandiTermNormalizer._display_case(label, language),
            "label_language": language,
            "method": method,
        }

    @staticmethod
    def _display_case(value, language):
        value = str(value).strip()
        if language == "en" and value:
            return value[0].upper() + value[1:]
        return value

    @staticmethod
    def _language(value):
        return "hi" if re.search(r"[\u0900-\u097f]", str(value)) else "en"

    def resolve(self, value, choices, field):
        requested = str(value or "").strip()
        if not requested:
            return requested, "blank", None
        choice_lookup = {_normal(choice): choice for choice in choices}
        direct = choice_lookup.get(_normal(requested))
        if direct is not None:
            return direct, "exact_catalog_match", None

        groups = {
            "crop": CROP_GROUPS,
            "district": DISTRICT_GROUPS,
            "market": self._market_alias_groups(),
        }.get(field, ())
        alias = self._group_match(requested, choice_lookup, groups)
        if alias is not None:
            return alias, "bilingual_alias", None

        source_language = (
            "hi" if re.search(r"[\u0900-\u097f]", requested) else "en"
        )
        target_language = "en" if source_language == "hi" else "hi"
        translator = self.translator
        if translator is None:
            translator = LocalTranslationService()
            self.translator = translator
        try:
            translated = translator.translate(
                requested, source_language, target_language
            )
        except (LocalTranslationError, OSError, ValueError):
            return requested, "unresolved", None
        translated_match = choice_lookup.get(_normal(translated))
        if translated_match is not None:
            return translated_match, "offline_translation", translated
        alias = self._group_match(translated, choice_lookup, groups)
        if alias is not None:
            return alias, "offline_translation_alias", translated
        return requested, "unresolved", translated

    @staticmethod
    def _group_match(value, choice_lookup, groups):
        normalized = _normal(value)
        for group in groups:
            if normalized not in {_normal(item) for item in group}:
                continue
            for item in group:
                choice = choice_lookup.get(_normal(item))
                if choice is not None:
                    return choice
        return None

    def _market_alias_groups(self):
        if self._market_groups is not None:
            return self._market_groups
        groups = list(MARKET_LABEL_GROUPS)
        if self.market_alias_path.exists():
            payload = yaml.safe_load(
                self.market_alias_path.read_text(encoding="utf-8")
            ) or {}
            for item in payload.get("aliases", []):
                values = [item.get("observed_name")]
                values.extend(item.get("query_names", []))
                groups.append(tuple(value for value in values if value))
        self._market_groups = tuple(groups)
        return self._market_groups
