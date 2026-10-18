"""Lazy, offline English-Hindi answer translation using MarianMT."""

import re


class LocalTranslationError(RuntimeError):
    """Raised when a configured local translation model cannot be used."""


class LocalTranslationService:
    MODELS = {
        ("en", "hi"): "Helsinki-NLP/opus-mt-en-hi",
        ("hi", "en"): "Helsinki-NLP/opus-mt-hi-en",
    }

    def __init__(self):
        self._loaded = {}

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
