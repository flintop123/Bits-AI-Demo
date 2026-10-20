import unittest

from services.local_translation_service import LocalTranslationService


class FakeTokenizer:
    def __call__(self, text, **kwargs):
        return {"input_ids": [[1, 2, 3]]}

    def batch_decode(self, outputs, skip_special_tokens):
        return ["  जैविक कॉरिडोर १३ जिलों में है।  "]


class FakeModel:
    def generate(self, **kwargs):
        return [[4, 5, 6]]


class LocalTranslationServiceTests(unittest.TestCase):
    def test_english_to_hindi_translation_is_normalized(self):
        service = LocalTranslationService()
        service._loaded[service.MODELS[("en", "hi")]] = (
            FakeTokenizer(),
            FakeModel(),
        )

        result = service.translate(
            "The organic corridor covers 13 districts.", "en", "hi"
        )

        self.assertEqual(result, "जैविक कॉरिडोर 13 जिलों में है।")

    def test_unsupported_language_pair_is_rejected(self):
        service = LocalTranslationService()

        with self.assertRaisesRegex(ValueError, "English-Hindi"):
            service.translate("bonjour", "fr", "hi")


if __name__ == "__main__":
    unittest.main()
