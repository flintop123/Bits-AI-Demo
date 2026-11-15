"""Lazy, offline English-Hindi answer translation using MarianMT."""

import re


class LocalTranslationError(RuntimeError):
    """Raised when a configured local translation model cannot be used."""


class LocalTranslationService:
    PROVIDER = "huggingface_transformers"
    MODEL_FAMILY = "MarianMT"
    MODELS = {
        ("en", "hi"): "Helsinki-NLP/opus-mt-en-hi",
        ("hi", "en"): "Helsinki-NLP/opus-mt-hi-en",
    }

    def __init__(self):
        self._loaded = {}

    @classmethod
    def translation_metadata(cls, source_language, target_language):
        """Describe the local model path without loading model weights."""
        source_language = str(source_language).lower()
        target_language = str(target_language).lower()
        if source_language == target_language:
            return {
                "provider": "identity",
                "model_family": None,
                "model_name": None,
                "source_language": source_language,
                "target_language": target_language,
                "execution": "not_required",
                "remote_api_used": False,
            }
        model_name = cls.MODELS.get((source_language, target_language))
        if not model_name:
            raise ValueError(
                "Only English-Hindi local translation is supported"
            )
        return {
            "provider": cls.PROVIDER,
            "model_family": cls.MODEL_FAMILY,
            "model_name": model_name,
            "source_language": source_language,
            "target_language": target_language,
            "execution": "local_inference",
            "remote_api_used": False,
        }

    def translate_with_metadata(
        self, text, source_language, target_language
    ):
        """Translate text and return auditable model metadata."""
        return {
            "text": self.translate(text, source_language, target_language),
            "translation_evidence": self.translation_metadata(
                source_language, target_language
            ),
        }

    def translate_many_with_metadata(
        self, texts, source_language, target_language, batch_size=32
    ):
        """Translate a bounded batch with one shared model evidence block."""
        return {
            "texts": self.translate_many(
                texts,
                source_language,
                target_language,
                batch_size=batch_size,
            ),
            "translation_evidence": self.translation_metadata(
                source_language, target_language
            ),
        }

    def translate(self, text, source_language, target_language):
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if not value:
            raise ValueError("translation text is required")
        source_language = str(source_language).lower()
        target_language = str(target_language).lower()
        if source_language == target_language:
            return value
        model_name = self.MODELS.get((source_language, target_language))
        if not model_name:
            raise ValueError(
                "Only English-Hindi local translation is supported"
            )

        tokenizer, model = self._model(model_name)
        try:
            inputs = tokenizer(
                value,
                return_tensors="pt",
                truncation=True,
                max_length=512,
            )
            outputs = model.generate(
                **inputs,
                num_beams=4,
                max_new_tokens=256,
            )
            translated = tokenizer.batch_decode(
                outputs, skip_special_tokens=True
            )[0]
        except Exception as exc:
            raise LocalTranslationError(
                f"Local translation failed using {model_name}: {exc}"
            ) from exc
        translated = re.sub(r"\s+", " ", translated).strip()
        translated = translated.translate(str.maketrans(
            "०१२३४५६७८९", "0123456789"
        ))
        if not translated:
            raise LocalTranslationError(
                f"Local translation returned no text using {model_name}"
            )
        return translated

    def translate_many(
        self, texts, source_language, target_language, batch_size=32
    ):
        """Translate short catalog labels in bounded local batches."""
        values = [re.sub(r"\s+", " ", str(text or "")).strip() for text in texts]
        if not values or any(not value for value in values):
            raise ValueError("translation texts must be non-empty")
        source_language = str(source_language).lower()
        target_language = str(target_language).lower()
        if source_language == target_language:
            return values
        model_name = self.MODELS.get((source_language, target_language))
        if not model_name:
            raise ValueError(
                "Only English-Hindi local translation is supported"
            )
        if not isinstance(batch_size, int) or not 1 <= batch_size <= 128:
            raise ValueError("batch_size must be between 1 and 128")

        tokenizer, model = self._model(model_name)
        translations = []
        try:
            for start in range(0, len(values), batch_size):
                batch = values[start:start + batch_size]
                inputs = tokenizer(
                    batch,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=128,
                )
                outputs = model.generate(
                    **inputs,
                    num_beams=4,
                    max_new_tokens=64,
                )
                translations.extend(tokenizer.batch_decode(
                    outputs, skip_special_tokens=True
                ))
        except Exception as exc:
            raise LocalTranslationError(
                f"Local translation failed using {model_name}: {exc}"
            ) from exc

        normalized = []
        for translated in translations:
            translated = re.sub(r"\s+", " ", translated).strip()
            translated = translated.translate(str.maketrans(
                "०१२३४५६७८९", "0123456789"
            ))
            if not translated:
                raise LocalTranslationError(
                    f"Local translation returned no text using {model_name}"
                )
            normalized.append(translated)
        return normalized

    def _model(self, model_name):
        if model_name in self._loaded:
            return self._loaded[model_name]
        try:
            from transformers import (
                AutoModelForSeq2SeqLM,
                AutoTokenizer,
            )

            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
            model.eval()
        except Exception as exc:
            raise LocalTranslationError(
                "Unable to load the offline translation model "
                f"{model_name}: {exc}"
            ) from exc
        self._loaded[model_name] = (tokenizer, model)
        return self._loaded[model_name]
