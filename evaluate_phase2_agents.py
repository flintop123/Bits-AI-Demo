"""Evaluate a Phase 2 orchestration trace with AgentEvals."""

import argparse
import json
import sys
from pathlib import Path

from phase2.evaluation import evaluate_trace


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("trace_file", help="JSON trace from run_phase2_pipeline.py")
    parser.add_argument("--output", help="Optional evaluation JSON output path")
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(argv)
        trace = json.loads(Path(args.trace_file).read_text(encoding="utf-8"))
        report = evaluate_trace(trace)
        print("\nPhase 2 agent evaluation")
        print("------------------------")
        print(f"Framework: {report['framework']}")
        print(f"Agents passed: {report['agents_passed']}/{report['agents_evaluated']}")
        for item in report["per_agent"]:
            print(f"{item['agent_id']}: {'PASS' if item['passed'] else 'FAIL'}")
        print(f"Overall: {'PASS' if report['passed'] else 'FAIL'}")
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"Evaluation file: {path.resolve()}")
        return 0 if report["passed"] else 1
    except Exception as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
