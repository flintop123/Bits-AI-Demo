"""Report saved paired intent-router results without loading or training a model."""

import argparse
import csv
import json
from pathlib import Path
import re


def summarize(rows):
    rows = list(rows)
    if not rows:
        raise ValueError("no held-out comparison rows")
    cases, hashes, checkpoints = set(), set(), set()
    scores = []
    for row in rows:
        case, digest = row.get("case_id"), row.get("case_sha256")
        if not case or case in cases or not digest or not re.fullmatch(r"[a-f0-9]{64}", digest) or digest in hashes:
            raise ValueError("comparison needs unique case IDs and valid, distinct SHA-256 hashes")
        if row.get("split") != "held_out" or row.get("training_overlap") != "0":
            raise ValueError("every comparison row must be held out with no training overlap")
        base, adapter = row.get("base_correct"), row.get("adapter_correct")
        if base not in {"0", "1"} or adapter not in {"0", "1"}:
            raise ValueError("correctness must be 0 or 1 per case")
        pair = (row.get("base_model"), row.get("adapter_model"))
        if not all(pair):
            raise ValueError("missing model checkpoint or adapter label")
        cases.add(case)
        hashes.add(digest)
        checkpoints.add(pair)
        scores.append((int(base), int(adapter)))
    if len(checkpoints) != 1:
        raise ValueError("comparison mixes different checkpoint or adapter labels")
    base_model, adapter = checkpoints.pop()
    size = len(scores)
    base_count = sum(x for x, _ in scores)
    adapter_count = sum(y for _, y in scores)
    return {
        "scope": "recorded QA intent routing only; not full QA accuracy and not deployed Qwen fine-tuning",
        "held_out_cases": size, "base_model": base_model, "adapter": adapter,
        "base_correct": base_count, "adapter_correct": adapter_count,
        "base_correct_pct": round(100 * base_count / size, 2),
        "adapter_correct_pct": round(100 * adapter_count / size, 2),
        "change_percentage_points": round(100 * (adapter_count - base_count) / size, 2),
        "fixed": sum(x < y for x, y in scores), "regressed": sum(x > y for x, y in scores),
        "unchanged_correct": sum(x == y == 1 for x, y in scores),
        "unchanged_incorrect": sum(x == y == 0 for x, y in scores),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path("eval/adapter_comparison.csv"))
    args = parser.parse_args(argv)
    try:
        with args.csv.open(encoding="utf-8-sig", newline="") as stream:
            report = summarize(csv.DictReader(stream, strict=True))
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"Comparison could not be summarized: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
