"""Genuine CPU-compatible LoRA comparison for QA intent routing.

This is an evaluation experiment, not a claim that the production Qwen model
was fine-tuned. It compares the same FLAN-T5 base checkpoint before and after a
PEFT LoRA adapter on the ten held-out QA cases.
"""

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LABELS = (
    "mandi_price", "mandi_intelligence", "crop_statistics",
    "document_search", "unsupported",
)


def canonical_hash(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def question_hash(question):
    normalized = re.sub(r"\s+", " ", str(question)).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def prompt(question):
    return (
        "Classify this Bihar agriculture question into exactly one label: "
        + ", ".join(LABELS) + ".\nQuestion: " + question + "\nLabel:"
    )


def normalize_label(text):
    value = str(text or "").strip().casefold().replace(" ", "_")
    for label in LABELS:
        if label in value:
            return label
    return value.splitlines()[0] if value else ""


class IntentDataset:
    def __init__(self, records, tokenizer, max_length=192):
        self.records = records
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        item = self.records[index]
        encoded = self.tokenizer(
            prompt(item["question"]), truncation=True,
            max_length=self.max_length, return_tensors="pt",
        )
        labels = self.tokenizer(
            text_target=item["intent"], truncation=True,
            max_length=24, return_tensors="pt",
        )["input_ids"]
        return {
            "input_ids": encoded["input_ids"].squeeze(0),
            "attention_mask": encoded["attention_mask"].squeeze(0),
            "labels": labels.squeeze(0),
        }


def predict(model, tokenizer, question, device):
    encoded = tokenizer(prompt(question), return_tensors="pt", truncation=True, max_length=192)
    encoded = {key: value.to(device) for key, value in encoded.items()}
    output = model.generate(**encoded, max_new_tokens=12, do_sample=False)
    return normalize_label(tokenizer.decode(output[0], skip_special_tokens=True))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="google/flan-t5-small")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--output", default="eval/adapter_comparison.csv")
    parser.add_argument("--adapter-dir", default="artifacts/adapters/intent-router-lora")
    args = parser.parse_args(argv)

    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, DataCollatorForSeq2Seq

    random.seed(17)
    torch.manual_seed(17)
    training = json.loads((ROOT / "eval/training/intent_router_train.json").read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "eval/cases/grounded_qa_agent.json").read_text(encoding="utf-8"))
    references = {
        x["case_id"]: x for x in json.loads(
            (ROOT / "eval/reference/grounded_qa_agent.json").read_text(encoding="utf-8")
        )
    }
    train_hashes = {question_hash(x["question"]) for x in training}
    case_hashes = {
        x["case_id"]: question_hash(x["input"]["question"])
        for x in cases
    }
    overlap = [case_id for case_id, digest in case_hashes.items() if digest in train_hashes]
    if overlap:
        raise ValueError(f"Held-out/training hash overlap: {overlap}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    base = AutoModelForSeq2SeqLM.from_pretrained(args.model).to(device)
    base_predictions = {
        case["case_id"]: predict(base, tokenizer, case["input"]["question"], device)
        for case in cases
    }

    config = LoraConfig(
        task_type=TaskType.SEQ_2_SEQ_LM, r=8, lora_alpha=16,
        lora_dropout=0.05, target_modules=["q", "v"],
    )
    model = get_peft_model(base, config)
    dataset = IntentDataset(training, tokenizer)
    collator = DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model)
    loader = DataLoader(dataset, batch_size=4, shuffle=True, collate_fn=collator)
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=5e-4,
    )
    model.train()
    for epoch in range(args.epochs):
        total_loss = 0.0
        for batch in loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            loss = model(**batch).loss
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach().cpu())
        print(f"epoch {epoch + 1}/{args.epochs}: loss={total_loss / max(len(loader), 1):.6f}")

    adapter_dir = ROOT / args.adapter_dir
    adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(adapter_dir)
    model.eval()
    rows = []
    for case in cases:
        case_id = case["case_id"]
        expected = references[case_id]["expected_intent"]
        base_prediction = base_predictions[case_id]
        adapter_prediction = predict(model, tokenizer, case["input"]["question"], device)
        base_correct = int(base_prediction == expected)
        adapter_correct = int(adapter_prediction == expected)
        rows.append({
            "case_id": case_id, "split": "held_out",
            "case_sha256": case_hashes[case_id], "base_model": args.model,
            "adapter_model": "intent-router-lora",
            "base_correct": base_correct, "adapter_correct": adapter_correct,
            "base_f1": base_correct, "adapter_f1": adapter_correct,
            "delta_f1": adapter_correct - base_correct, "training_overlap": 0,
            "notes": f"expected={expected}; base={base_prediction}; adapter={adapter_prediction}",
        })
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print(f"Device: {device}")
    print(f"Training/held-out hash overlap: 0")
    print(f"Base correct: {sum(x['base_correct'] for x in rows)}/{len(rows)}")
    print(f"Adapter correct: {sum(x['adapter_correct'] for x in rows)}/{len(rows)}")
    print(f"Comparison: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
