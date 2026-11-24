"""Read-only check of bilingual labels against an independently reviewed key."""

import argparse
import json
import os
from pathlib import Path
import re
import unicodedata

from services.mandi_term_normalizer import MandiTermNormalizer

_FIELDS = {"crop", "market", "district", "variety"}
_LANGUAGE = {"en", "hi"}
_MODEL_METHODS = {"offline_translation", "agentic_offline_translation"}


def _key(text):
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", text.strip())).casefold()


def load_cases(path):
    cases = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(cases, list) or not 1 <= len(cases) <= 30:
        raise ValueError("the review key must contain 1–30 cases")
    seen = set()
    for case in cases:
        required = {"id", "official_value", "target_language", "field", "expected_labels"}
        if not isinstance(case, dict) or not required <= case.keys() or case.keys() - (required | {"require_model"}):
            raise ValueError("each case must specify only the documented key fields")
        for field in ("id", "official_value", "target_language", "field"):
            value = case[field]
            if not isinstance(value, str) or not value or value != value.strip() or len(value) > 200:
                raise ValueError(f"{field} must be nonblank, trimmed text (max 200 characters)")
        if case["target_language"] not in _LANGUAGE or case["field"] not in _FIELDS:
            raise ValueError("unsupported language or catalogue field")
        if case["id"] in seen:
            raise ValueError(f"duplicate case ID: {case['id']}")
        seen.add(case["id"])
        labels = case["expected_labels"]
        if not isinstance(labels, list) or not 1 <= len(labels) <= 10 or not all(
            isinstance(label, str) and label.strip() and len(label) <= 200 for label in labels
        ):
            raise ValueError("expected_labels must contain 1–10 independently reviewed strings")
        if type(case.get("require_model", False)) is not bool:
            raise ValueError("require_model must be a Boolean")
    return cases


def evaluate_cases(cases, normalizer):
    rows = []
    for case in cases:
        official = case["official_value"]
        language = case["target_language"]
        # The model sees the source value, not the independently reviewed labels.
        options = normalizer.localized_options([official], case["field"], language)
        option = options[0] if len(options) == 1 else {}
        evidence = option.get("translation_evidence", {})
        label = option.get("label")
        method = option.get("method", "")
        errors = []
        if option.get("value") != official or evidence.get("official_value_preserved") is not True:
            errors.append("official_value_not_preserved")
        if option.get("label_language") != language:
            errors.append("target_language_not_returned")
        if not isinstance(label, str) or _key(label) not in {
            _key(accepted) for accepted in case["expected_labels"]
        }:
            errors.append("label_not_in_review_key")
        used_model = method in _MODEL_METHODS and bool(evidence.get("model_name"))
        if case.get("require_model", False) and not used_model:
            errors.append("no_accepted_model_label")
        rows.append({
            "id": case["id"], "official_value": official,
            "target_language": language, "field": case["field"],
            "expected_labels": case["expected_labels"], "observed": option,
            "accepted_model_label": used_model, "errors": errors,
        })
    passed = sum(not result["errors"] for result in rows)
    return {
        "cases": len(rows), "passed": passed, "failed": len(rows) - passed,
        "accepted_model_labels": sum(row["accepted_model_label"] for row in rows),
        "basis": "independently reviewed labels, not model confidence",
        "database_writes": False, "results": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--lookup-only", action="store_true",
                        help="Disable model calls; unrecognized terms will retain source labels")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.key)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.lookup_only:
        class NoModel:
            @staticmethod
            def translate(*_):
                from services.local_translation_service import LocalTranslationError
                raise LocalTranslationError("Model inference disabled for this check")

        normalizer = MandiTermNormalizer(translator=NoModel(), translation_agent=False)
    else:
        # Cache-only model load and a bounded loopback call. The first download
        # of model weights, if needed, is separate from this acceptance run.
        os.environ["HF_HUB_OFFLINE"] = "1"
        from services.catalog_translation_agent import CatalogTranslationAgent
        from services.local_translation_service import LocalTranslationService
        from services.ollama_client import OllamaClient

        translator = LocalTranslationService()
        normalizer = MandiTermNormalizer(
            translator=translator,
            translation_agent=CatalogTranslationAgent(
                llm=OllamaClient(base_url="http://127.0.0.1:11434", timeout=60),
                back_translator=translator,
            ),
        )

    report = evaluate_cases(cases, normalizer)
    report["mode"] = "lookup_only" if args.lookup_only else "local_model_enabled"
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return int(bool(report["failed"]))


if __name__ == "__main__":
    raise SystemExit(main())
