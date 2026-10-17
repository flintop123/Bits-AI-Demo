"""Run the independent Phase 2 evaluation suite and save its evidence."""

import argparse
import json
import sys
from pathlib import Path

from phase2.evaluation_suite import (
    DEFAULT_CASE_MANIFEST,
    load_evaluation_cases,
    run_evaluation_suite,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_CASE_MANIFEST))
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument(
        "--output", default="artifacts/phase2/final_evaluation_suite.json"
    )
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(argv)
        cases = load_evaluation_cases(args.manifest)
        if args.case_ids:
            requested = set(args.case_ids)
            cases = [case for case in cases if case["id"] in requested]
            missing = requested - {case["id"] for case in cases}
            if missing:
                raise ValueError("Unknown case(s): " + ", ".join(sorted(missing)))
        report = run_evaluation_suite(cases)
        print("\nPhase 2 final evaluation suite")
        print("------------------------------")
        for item in report["results"]:
            retry = " (transient retry)" if item["fault_injection"] else ""
            print(
                f"{item['case_id']}: "
                f"{'PASS' if item['passed'] else 'FAIL'}{retry}"
            )
        print(
            f"Overall: {report['cases_passed']}/"
            f"{report['cases_evaluated']} cases passed"
        )
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"Evidence file: {path.resolve()}")
        return 0 if report["passed"] else 1
    except Exception as exc:
        print(f"Phase 2 evaluation suite failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
