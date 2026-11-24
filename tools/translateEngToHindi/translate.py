"""Jitendra's Hindi-to-English PDF translation, as a derived review aid."""

import argparse
import re
from pathlib import Path

import torch
from pypdf import PdfReader
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

MODEL_NAME = "Helsinki-NLP/opus-mt-hi-en"


class Translator:
    model_name = MODEL_NAME

    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name).to(self.device)
        self.model.eval()

    def translate(self, text, batch_size=8):
        if not isinstance(text, str) or not text.strip():
            return ""
        if not 1 <= batch_size <= 16:
            raise ValueError("Translation batch size must be 1–16")
        segments = [part.strip() for part in re.split(r"(?<=[।.?!])\s+|\n+", text) if part.strip()]
        for segment in segments:
            if len(self.tokenizer.encode(segment, add_special_tokens=True)) > 512:
                raise ValueError("A translation segment exceeds 512 tokens; review or split the source chunk")
        results = []
        for start in range(0, len(segments), batch_size):
            inputs = self.tokenizer(
                segments[start:start + batch_size], padding=True, truncation=False, return_tensors="pt",
            ).to(self.device)
            with torch.inference_mode():
                outputs = self.model.generate(**inputs, num_beams=4, max_new_tokens=512)
            translated = self.tokenizer.batch_decode(outputs, skip_special_tokens=True)
            if len(translated) != len(segments[start:start + batch_size]) or any(not row.strip() for row in translated):
                raise RuntimeError("Translation omitted one or more source segments")
            results.extend(row.strip() for row in translated)
        return " ".join(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    source = "\n".join(page.extract_text() or "" for page in PdfReader(args.input).pages)
    print(Translator().translate(source))
