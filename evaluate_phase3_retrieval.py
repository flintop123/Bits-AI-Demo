"""Run and persist the Phase 3 hybrid retrieval evaluation."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from phase3.retrieval_evaluation import (
    DEFAULT_MANIFEST,
    evaluate_retrieval,
    load_retrieval_cases,
)
from services.agriculture_query_service import AgricultureQueryService


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--output", default="artifacts/phase3/retrieval_evaluation.json"
    )
    return parser.parse_args(argv)


def main(argv=None):
    service = None
    try:
        args = parse_args(argv)
        cases, acceptance = load_retrieval_cases(args.manifest)
        service = AgricultureQueryService()
        report = evaluate_retrieval(
            service, cases, limit=args.limit, acceptance=acceptance
        )
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        report["manifest"] = str(Path(args.manifest).resolve())
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print("\nPhase 3 multilingual retrieval evaluation")
        print("-----------------------------------------")
        for item in report["results"]:
            print(
                f"{item['case_id']}: "
                f"keyword={item['keyword']['rank'] or 'MISS'}, "
                f"hybrid={item['hybrid']['rank'] or 'MISS'}"
            )
        metrics = report["metrics"]
        print(
            "Keyword Hit@5 / MRR@5: "
            f"{metrics['keyword_hit_rate_at_k']:.2%} / "
            f"{metrics['keyword_mrr_at_k']:.4f}"
        )
        print(
            "Hybrid Hit@5 / MRR@5: "
            f"{metrics['hybrid_hit_rate_at_k']:.2%} / "
            f"{metrics['hybrid_mrr_at_k']:.4f}"
        )
        print(
            "Cross-language hits: "
            f"{metrics['cross_language_hits_at_k']}/"
            f"{metrics['cross_language_cases']}"
        )
        print(f"Overall: {'PASS' if report['passed'] else 'FAIL'}")
        print(f"Evidence file: {path.resolve()}")
        return 0 if report["passed"] else 1
    except Exception as exc:
        print(f"Phase 3 evaluation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if service is not None:
            service.close()


if __name__ == "__main__":
    raise SystemExit(main())
