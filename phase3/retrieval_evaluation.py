"""Labelled evaluation for multilingual hybrid document retrieval."""

from copy import deepcopy
from pathlib import Path

import yaml

from services.multilingual_query_expansion import expand_document_query


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "sources" / "phase3_retrieval_cases.yaml"


def load_retrieval_cases(path=DEFAULT_MANIFEST):
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Phase 3 manifest must contain non-empty cases")
    seen = set()
    validated = []
    for raw in cases:
        case = deepcopy(raw)
        case_id = str(case.get("id", "")).strip()
        query = str(case.get("query", "")).strip()
        expected = case.get("expected_source_ids")
        if not case_id or case_id in seen:
            raise ValueError("Phase 3 case ids must be non-empty and unique")
        if not query:
            raise ValueError(f"Case {case_id} must contain a query")
        if not isinstance(expected, list) or not expected:
            raise ValueError(f"Case {case_id} needs expected_source_ids")
        case["id"] = case_id
        case["query"] = query
        case["keyword_query"] = str(
            case.get("keyword_query") or query
        ).strip()
        case["expected_source_ids"] = [str(value) for value in expected]
        seen.add(case_id)
        validated.append(case)
    return validated, payload.get("acceptance", {})


def _rank_expected(records, expected_source_ids):
    expected = set(expected_source_ids)
    for rank, record in enumerate(records, start=1):
        if record.get("source_id") in expected:
            return rank
    return None


def _source_ids(records):
    return [record.get("source_id") for record in records]


def evaluate_retrieval(query_service, cases, *, limit=5, acceptance=None):
    if limit < 1 or limit > 20:
        raise ValueError("evaluation limit must be between 1 and 20")
    acceptance = acceptance or {}
    results = []
    for case in cases:
        keyword_records = query_service.search_agriculture_documents(
            case["keyword_query"], limit
        )
        hybrid_records = query_service.search_agriculture_documents(
            expand_document_query(
                case["keyword_query"], case["query"], max_length=200
            ),
            limit,
            semantic_query=expand_document_query(
                case["query"], case["keyword_query"], max_length=500
            ),
        )
        keyword_rank = _rank_expected(
            keyword_records, case["expected_source_ids"]
        )
        hybrid_rank = _rank_expected(
            hybrid_records, case["expected_source_ids"]
        )
        results.append({
            "case_id": case["id"],
            "language": case.get("language"),
            "cross_language": bool(case.get("cross_language")),
            "query": case["query"],
            "expected_source_ids": case["expected_source_ids"],
            "keyword": {
                "hit": keyword_rank is not None,
                "rank": keyword_rank,
                "reciprocal_rank": 1 / keyword_rank if keyword_rank else 0,
                "source_ids": _source_ids(keyword_records),
            },
            "hybrid": {
                "hit": hybrid_rank is not None,
                "rank": hybrid_rank,
                "reciprocal_rank": 1 / hybrid_rank if hybrid_rank else 0,
                "source_ids": _source_ids(hybrid_records),
                "retrieval_modes": [
                    record.get("retrieval", {}).get("mode")
                    for record in hybrid_records
                ],
            },
        })

    total = len(results)
    hybrid_hits = sum(item["hybrid"]["hit"] for item in results)
    keyword_hits = sum(item["keyword"]["hit"] for item in results)
    cross_language = [
        item for item in results if item["cross_language"]
    ]
    cross_hits = sum(item["hybrid"]["hit"] for item in cross_language)
    metrics = {
        "cases": total,
        "keyword_hit_rate_at_k": round(keyword_hits / total, 4),
        "hybrid_hit_rate_at_k": round(hybrid_hits / total, 4),
        "keyword_mrr_at_k": round(sum(
            item["keyword"]["reciprocal_rank"] for item in results
        ) / total, 4),
        "hybrid_mrr_at_k": round(sum(
            item["hybrid"]["reciprocal_rank"] for item in results
        ) / total, 4),
        "cross_language_cases": len(cross_language),
        "cross_language_hits_at_k": cross_hits,
    }
    checks = {
        "minimum_hybrid_hit_rate": metrics["hybrid_hit_rate_at_k"]
        >= float(acceptance.get("min_hybrid_hit_rate_at_k", 0.8)),
        "minimum_cross_language_hits": cross_hits
        >= int(acceptance.get("min_cross_language_hits_at_k", 2)),
        "hybrid_not_worse_than_keyword": metrics["hybrid_hit_rate_at_k"]
        >= metrics["keyword_hit_rate_at_k"],
        "semantic_path_observed": any(
            mode in {"semantic", "hybrid"}
            for item in results
            for mode in item["hybrid"]["retrieval_modes"]
        ),
    }
    return {
        "framework": "labelled bilingual retrieval evaluation",
        "limit": limit,
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "results": results,
    }
