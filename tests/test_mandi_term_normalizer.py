import unittest
from unittest.mock import Mock

from services.mandi_term_normalizer import MandiTermNormalizer


class FakeTranslator:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def translate(self, text, source_language, target_language):
        self.calls.append((text, source_language, target_language))
        return self.output


class MandiTermNormalizerTests(unittest.TestCase):
    def test_unknown_hindi_market_is_transliterated_not_translated(self):
        class TranslatorThatMustNotRun:
            def translate_many(self, *args, **kwargs):
                raise AssertionError("market proper names must not be translated")

        normalizer = MandiTermNormalizer(
            translator=TranslatorThatMustNotRun(),
            market_alias_path="missing-market-aliases.yaml",
        )
        options = normalizer.localized_options(["रफीगंज"], "market", "en")
        self.assertEqual(options[0]["value"], "रफीगंज")
        self.assertEqual(options[0]["label"], "Rafiganj")
        self.assertEqual(
            options[0]["method"], "devanagari_transliteration"
        )

    def test_market_suffixes_are_removed_before_transliteration(self):
        normalizer = MandiTermNormalizer(
            market_alias_path="missing-market-aliases.yaml"
        )
        options = normalizer.localized_options(
            ["मानसी मंडी (नया)"], "market", "en"
        )
        self.assertEqual(options[0]["label"], "Manasi")

    def test_english_crop_resolves_to_hindi_catalog_value(self):
        normalizer = MandiTermNormalizer()
        resolved, method, translated = normalizer.resolve(
            "Potato", ["आलू", "प्याज"], "crop"
        )
        self.assertEqual(resolved, "आलू")
        self.assertEqual(method, "bilingual_alias")
        self.assertIsNone(translated)

    def test_hindi_crop_resolves_to_english_catalog_value(self):
        normalizer = MandiTermNormalizer()
        resolved, method, _ = normalizer.resolve(
            "आलू", ["Potato", "Onion"], "crop"
        )
        self.assertEqual(resolved, "Potato")
        self.assertEqual(method, "bilingual_alias")

    def test_english_district_resolves_to_hindi(self):
        normalizer = MandiTermNormalizer()
        resolved, method, _ = normalizer.resolve(
            "Arwal", ["अरवल", "पटना"], "district"
        )
        self.assertEqual(resolved, "अरवल")
        self.assertEqual(method, "bilingual_alias")

    def test_reviewed_market_alias_is_used(self):
        normalizer = MandiTermNormalizer()
        resolved, method, _ = normalizer.resolve(
            "Daudnagar", ["दाउनगर", "अरवल"], "market"
        )
        self.assertEqual(resolved, "दाउनगर")
        self.assertEqual(method, "bilingual_alias")

    def test_latin_official_market_has_reviewed_hindi_display_alias(self):
        normalizer = MandiTermNormalizer()
        options = normalizer.localized_options(
            ["Samastipur APMC"], "market", "hi"
        )
        self.assertEqual(options[0]["value"], "Samastipur APMC")
        self.assertEqual(options[0]["label"], "समस्तीपुर एपीएमसी")
        self.assertEqual(options[0]["method"], "reviewed_bilingual_alias")

        resolved, method, _ = normalizer.resolve(
            "समस्तीपुर एपीएमसी", ["Samastipur APMC"], "market"
        )
        self.assertEqual(resolved, "Samastipur APMC")
        self.assertEqual(method, "bilingual_alias")

    def test_offline_translation_must_match_catalog(self):
        translator = FakeTranslator("परीक्षित फसल")
        normalizer = MandiTermNormalizer(translator=translator)
        resolved, method, translated = normalizer.resolve(
            "tested crop", ["परीक्षित फसल"], "crop"
        )
        self.assertEqual(resolved, "परीक्षित फसल")
        self.assertEqual(method, "offline_translation")
        self.assertEqual(translated, "परीक्षित फसल")

    def test_unmatched_translation_is_not_accepted(self):
        normalizer = MandiTermNormalizer(
            translator=FakeTranslator("अन्य शब्द")
        )
        resolved, method, translated = normalizer.resolve(
            "unknown", ["आलू"], "crop"
        )
        self.assertEqual(resolved, "unknown")
        self.assertEqual(method, "unresolved")
        self.assertEqual(translated, "अन्य शब्द")

    def test_dropdown_options_are_exactly_the_live_catalog_values(self):
        translator = Mock()
        translator.translate_many.return_value = ["Horse gram"]
        normalizer = MandiTermNormalizer(translator=translator)

        options = normalizer.localized_options(
            ["कुलथी"], "crop", "en"
        )

        self.assertEqual([item["value"] for item in options], ["कुलथी"])
        self.assertEqual(options[0]["label"], "Horse gram")
        self.assertEqual(options[0]["method"], "offline_translation")

    def test_dropdown_preserves_value_when_only_label_is_translated(self):
        normalizer = MandiTermNormalizer()
        options = normalizer.localized_options(
            ["आलू", "प्याज"], "crop", "en"
        )

        self.assertEqual(
            {item["value"] for item in options}, {"आलू", "प्याज"}
        )
        self.assertEqual(
            {item["label"] for item in options}, {"Potato", "Onion"}
        )


if __name__ == "__main__":
    unittest.main()
