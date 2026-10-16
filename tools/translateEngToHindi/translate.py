
from deep_translator import GoogleTranslator
import time

translator = GoogleTranslator(source="hi", target="en")
translation_cache = {}

def translate_text(value):
    if not isinstance(value, str) or not value.strip():
        return value

    value = value.strip()

    if value in translation_cache:
        return translation_cache[value]

    try:
        # Translate a single text
        translated = translator.translate(value)

        translation_cache[value] = translated
        print(f"{value} -> {translated}")

        # Small delay before the next translation request
        time.sleep(1)
        return translated

    except Exception as exc:
        print(f"Translation failed for {value!r}: {exc}")
        return value


# print(translate_text("कृषि मंडी"))



from transformers import pipeline

# Downloads the model on first use.
# After downloading, it can run locally.
translator = pipeline(
    "translation",
    model="Helsinki-NLP/opus-mt-hi-en"
)

def translate_text(text):
    if not isinstance(text, str) or not text.strip():
        return text

    try:
        result = translator(text.strip(), max_length=128)
        return result[0]["translation_text"]
    except Exception as exc:
        print(f"Translation failed for {text!r}: {exc}")
        return text


if __name__ == "__main__":
    print(translate_text("कृषि मंडी"))
    print(translate_text("सिवान"))
    print(translate_text("आज आलू की कीमत 1600 रुपये प्रति क्विंटल है।"))



"""
Hindi -> English translation agent powered by Claude.

Setup:
    pip install anthropic
    export ANTHROPIC_API_KEY="your-key"

Usage:
    python hindi_to_english_agent.py "मुझे चाय पसंद है"          # one-off
    python hindi_to_english_agent.py --file input.txt            # translate a file
    python hindi_to_english_agent.py                             # interactive chat mode
"""

"""
Free, offline Hindi -> English translator (no API key, no per-use cost).

Default model : AI4Bharat IndicTrans2 (distilled 200M) - best quality for Hindi, runs on CPU.
Lighter option: Helsinki-NLP opus-mt-hi-en - smaller, simpler, a bit lower quality.

Setup:
    pip install torch transformers sentencepiece sacremoses
    pip install git+https://github.com/VarunGumma/IndicTransToolkit.git   # needed for IndicTrans2

Usage:
    python hindi_to_english_free.py "मुझे चाय पसंद है"
    python hindi_to_english_free.py --file input.txt
    python hindi_to_english_free.py --model opus "मुझे चाय पसंद है"
    python hindi_to_english_free.py            # interactive mode

The first run downloads the model from Hugging Face (internet needed once), then it works offline.
"""


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


class Translator:
    def __init__(self):
        print(f"Loading {MODEL_NAME} on {DEVICE} ...", file=sys.stderr)

        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
        self.model.to(DEVICE)
        self.model.eval()

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
                    max_new_tokens=128,
                )

            translated = self.tokenizer.batch_decode(
                outputs,
                skip_special_tokens=True,
            )
            results.extend(translated)

        return " ".join(result.strip() for result in results).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate Hindi text to English locally using OPUS-MT."
    )
    parser.add_argument("text", nargs="?", help="Hindi text to translate")
    parser.add_argument("--file", help="UTF-8 text file to translate")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Number of sentences to translate per batch (default: 8)",
    )
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")

    if args.file and args.text:
        parser.error("Provide either text or --file, not both")

    try:
        translator = Translator()

        if args.file:
            with open(args.file, "r", encoding="utf-8") as file:
                print(translator.translate(file.read(), args.batch_size))

        elif args.text:
            print(translator.translate(args.text, args.batch_size))

        else:
            print("Hindi to English translator. Type 'quit' to exit.\n")

            while True:
                try:
                    text = input("हिंदी > ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break

                if text.lower() in {"quit", "exit", "q"}:
                    break

                if text:
                    print(
                        "English > "
                        + translator.translate(text, args.batch_size)
                        + "\n"
                    )

    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
