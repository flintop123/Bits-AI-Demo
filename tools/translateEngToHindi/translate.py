
import argparse
import re
import sys

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

MODEL_NAME = "Helsinki-NLP/opus-mt-hi-en"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def split_sentences(text: str) -> list[str]:
    """Split text at sentence endings and newlines."""
    parts = re.split(r"(?<=[।.?!])\s+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


from pypdf import PdfReader

from pathlib import Path
from pypdf import PdfReader

# 1. Use a raw string (r"...") so backslashes aren't treated as escape characters
pdf_path = Path(r"C:\\Users\\JitendraKumar\\Downloads\\apeda_makhana_report_hindi-1-5.pdf")

def extract_pdf(path: Path) -> str:
    # Verify existence with pathlib
    if not path.is_file():
        raise FileNotFoundError(f"Python cannot see the file at: {path}")

    reader = PdfReader(path)
    text_content = []
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text_content.append(extracted)

    return "\n".join(text_content)




class Translator:
    def __init__(self):
        print(f"Loading {MODEL_NAME} on {DEVICE} ...", file=sys.stderr)

        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME).to(DEVICE)

        print("Translator ready.", file=sys.stderr)

    def translate(self, text: str, batch_size: int = 8) -> str:
        """Translate Hindi text into English in batches."""
        if not text or not text.strip():
            return ""

        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")

        sentences = split_sentences(text)
        results = []

        for start in range(0, len(sentences), batch_size):
            batch = sentences[start:start + batch_size]

            inputs = self.tokenizer(
                batch,
                truncation=True,
                padding=True,
                max_length=512,
                return_tensors="pt",
            ).to(DEVICE)

            with torch.inference_mode():
                outputs = self.model.generate(
                    **inputs,
                    num_beams=4,
                    max_new_tokens=512,
                )

            translated = self.tokenizer.batch_decode(
                outputs,
                skip_special_tokens=True,
            )
            results.extend(translated)

        return " ".join(result.strip() for result in results).strip()


def main() -> None:
    try:
        text_content = extract_pdf(pdf_path)
        # englisth_content = translates("अनाज या अनाज उतपािों को फु लाकर या भूनकर प्राप्त िाद्य पिाथ्व", 8)
        # print(f"Successfully extracted {len(text)} characters from PDF.")
        englisth_content = Translator().translate(text_content, 8)
        print(englisth_content)
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
