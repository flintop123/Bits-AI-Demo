"""Live regression check for Hindi-to-English-source grounded QA."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from services.agriculture_qa_service import AgricultureQAService


QUESTION = "गंगा नदी के किनारे जैविक कॉरिडोर कितने जिलों में स्थापित किया गया है?"
EXPECTED_SOURCE = "bihar_annual_scheme_2022_23"


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="docs/evidence/phase3_hindi_corridor_smoke.json",
    )
    return parser.parse_args(argv)


def main(argv=None):
    service = None
    try:
        args = parse_args(argv)
        service = AgricultureQAService()
        result = service.ask(QUESTION, answer_language="hi")
        retrieved_source_ids = sorted({
            record.get("source_id")
            for record in result.get("records", [])
            if record.get("source_id")
        })
        cited_source_ids = sorted({
            source.get("source_id")
            for source in result.get("sources", [])
            if source.get("source_id")
        })
        checks = {
            "document_intent": result.get("intent") == "document_search",
            "hindi_answer": result.get("answer_language") == "hi",
            "expected_source_retrieved": EXPECTED_SOURCE
            in retrieved_source_ids,
            "expected_source_cited": EXPECTED_SOURCE in cited_source_ids,
            "citations_match_answer_evidence": cited_source_ids
            == [EXPECTED_SOURCE],
            "district_count_answered": (
                "13" in result.get("answer", "")
                or "१३" in result.get("answer", "")
            ),
            "citations_returned": bool(result.get("sources")),
            "hybrid_retrieval": result.get("retrieval", {}).get("mode")
            == "hybrid",
        }
        evidence = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "question": QUESTION,
            "answer": result.get("answer"),
            "answer_language": result.get("answer_language"),
            "intent": result.get("intent"),
            "filters": result.get("filters"),
            "retrieval": result.get("retrieval"),
            "retrieved_source_ids": retrieved_source_ids,
            "cited_source_ids": cited_source_ids,
            "sources": result.get("sources", []),
            "checks": checks,
            "passed": all(checks.values()),
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        print("\nPhase 3 Hindi corridor live QA")
        print("--------------------------------")
        print(f"Intent: {evidence['intent']}")
        print(f"Retrieval: {evidence['retrieval']}")
        print(
            "Retrieved candidates: "
            f"{', '.join(retrieved_source_ids) or 'none'}"
        )
        print(
            "Cited answer evidence: "
            f"{', '.join(cited_source_ids) or 'none'}"
        )
        print(f"Answer: {evidence['answer']}")
        print(f"Overall: {'PASS' if evidence['passed'] else 'FAIL'}")
        print(f"Evidence file: {output.resolve()}")
        return 0 if evidence["passed"] else 1
    except Exception as exc:
        print(f"Live Hindi corridor QA failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if service is not None:
            service.close()


if __name__ == "__main__":
    raise SystemExit(main())
