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

    def test_translation_metadata_identifies_local_marian_model(self):
        metadata = LocalTranslationService.translation_metadata("hi", "en")

        self.assertEqual(metadata["model_family"], "MarianMT")
        self.assertEqual(
            metadata["model_name"], "Helsinki-NLP/opus-mt-hi-en"
        )
        self.assertEqual(metadata["execution"], "local_inference")
        self.assertFalse(metadata["remote_api_used"])

    def test_translate_with_metadata_returns_text_and_model_evidence(self):
        service = LocalTranslationService()
        service._loaded[service.MODELS[("en", "hi")]] = (
            FakeTokenizer(),
            FakeModel(),
        )

        result = service.translate_with_metadata(
            "The organic corridor covers 13 districts.", "en", "hi"
        )

        self.assertEqual(result["text"], "जैविक कॉरिडोर 13 जिलों में है।")
        self.assertEqual(
            result["translation_evidence"]["model_name"],
            "Helsinki-NLP/opus-mt-en-hi",
        )


if __name__ == "__main__":
    unittest.main()
