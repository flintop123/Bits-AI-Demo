import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.verify_bilingual_intake import evaluate_cases, load_cases
from services.mandi_term_normalizer import MandiTermNormalizer


CASE = {
    "id": "hindi-crop", "official_value": "कुलथी", "field": "crop",
    "target_language": "en", "expected_labels": ["Horse gram"],
}


class BilingualIntakeTests(unittest.TestCase):
    def test_reviewed_label_passes_but_is_not_model_evidence(self):
        result = evaluate_cases([CASE], MandiTermNormalizer(translation_agent=False))
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["accepted_model_labels"], 0)
        self.assertFalse(result["database_writes"])

    def test_reviewed_label_cannot_satisfy_model_requirement(self):
        result = evaluate_cases(
            [{**CASE, "require_model": True}], MandiTermNormalizer(translation_agent=False)
        )
        self.assertEqual(result["failed"], 1)
        self.assertIn("no_accepted_model_label", result["results"][0]["errors"])

    def test_evaluator_key_does_not_enter_model_and_value_is_checked(self):
        class Normalizer:
            def localized_options(self, values, field, lang):
                self.call = (values, field, lang)
                return [{
                    "value": "incorrect", "label": "Horse Gram",
                    "label_language": "en", "method": "offline_translation",
                    "translation_evidence": {
                        "model_name": "fixture", "official_value_preserved": True,
                    },
                }]

        normalizer = Normalizer()
        result = evaluate_cases([CASE], normalizer)
        self.assertEqual(normalizer.call, (["कुलथी"], "crop", "en"))
        self.assertEqual(result["results"][0]["errors"], ["official_value_not_preserved"])

    def test_review_key_rejects_duplicate_ids_and_non_boolean_values(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "key.json"
            for cases in ([CASE, CASE], [{**CASE, "require_model": "false"}]):
                path.write_text(json.dumps(cases), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_cases(path)


if __name__ == "__main__":
    unittest.main()
