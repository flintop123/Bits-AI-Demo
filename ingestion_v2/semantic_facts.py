"""Evidence-anchored semantic fact extraction from unfamiliar PDF layouts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ingestion_v2.pdf_sections import heading_for_evidence
from ingestion_v2.models import (
    ExtractSemanticFactsInput,
    ExtractSemanticFactsOutput,
    FieldProvenance,
    MappedRecord,
    SemanticFactBatchProposal,
    SemanticFactCandidate,
    SourceModality,
    TargetCollection,
)


class _SemanticFactEnvelope(BaseModel):
    """Require a facts list without discarding siblings on candidate failure."""

    model_config = ConfigDict(extra="forbid")
    facts: list[Any] = Field(strict=True)


class CanonicalAgricultureFact(BaseModel):
    """Validated structured fact with immutable source evidence."""

    model_config = ConfigDict(extra="allow")

    fact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_type: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    value_as_reported: str = Field(min_length=1)
    normalized_value: float | None = Field(default=None, ge=0)
    unit_as_reported: str | None = None
    normalized_unit: str | None = None
    period: str | None = None
    geography: str | None = None
    crop: str | None = None
    scheme_name: str | None = None
    evidence_quote: str = Field(min_length=1)
    evidence_validation: Literal["exact_quote", "normalized_whitespace_quote"]
    normalization_status: Literal[
        "not_provided",
        "verified_against_reported_value_and_unit",
        "model_proposed_requires_review",
    ]
    review_status: Literal["approved_for_write", "human_review_required"]
    page_number: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    source_file: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_hash: str = Field(min_length=64, max_length=64)
    extraction_run_id: str = Field(min_length=1)


def _normalized_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _signature(candidate: SemanticFactCandidate, source_hash: str):
    values = (
        source_hash,
        candidate.fact_type,
        candidate.subject,
        candidate.metric,
        candidate.value_as_reported,
        candidate.unit_as_reported,
        candidate.period,
        candidate.geography,
        candidate.crop,
        candidate.scheme_name,
        _normalized_text(candidate.evidence_quote),
    )
    normalized = "|".join(_normalized_text(value).casefold() for value in values)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _evidence_location(content, quote):
    direct_start = content.find(quote)
    if direct_start >= 0:
        return "exact_quote", direct_start, direct_start + len(quote)
    if _normalized_text(quote) in _normalized_text(content):
        return "normalized_whitespace_quote", None, None
    return None, None, None


UNIT_ALIASES = {
    "percent": {"percent", "percentage", "%", "प्रतिशत"},
    "hectare": {"hectare", "hectares", "ha", "हेक्टेयर"},
    "tonne": {"tonne", "tonnes", "metric tonne", "metric tonnes", "टन"},
    "kg_per_hectare": {
        "kg/ha", "kg per hectare", "kg_per_hectare", "किलोग्राम/हेक्टेयर",
    },
    "count": {"count", "number", "संख्या"},
}


def _reported_number(value):
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", str(value or ""))
    return float(match.group(0).replace(",", "")) if match else None


def _unit_is_verified(reported, normalized):
    if normalized in (None, ""):
        return True
    reported = _normalized_text(reported).casefold()
    normalized = _normalized_text(normalized).casefold()
    if reported == normalized:
        return True
    aliases = UNIT_ALIASES.get(normalized)
    return bool(aliases and reported in aliases)


def _normalization_status(candidate):
    if candidate.normalized_value is None and not candidate.normalized_unit:
        return "not_provided"
    reported = _reported_number(candidate.value_as_reported)
    value_matches = (
        candidate.normalized_value is None
        or (
            reported is not None
            and abs(candidate.normalized_value - reported)
            <= max(1e-9, abs(reported) * 1e-9)
        )
    )
    if value_matches and _unit_is_verified(
        candidate.unit_as_reported, candidate.normalized_unit
    ):
        return "verified_against_reported_value_and_unit"
    return "model_proposed_requires_review"


def _candidate_data(candidate, request, source_record, evidence_status):
    locator = source_record.record_locator
    fact_id = _signature(candidate, request.inspection.source_hash)
    return {
        "fact_id": fact_id,
        "fact_type": candidate.fact_type,
        "subject": _normalized_text(candidate.subject),
        "metric": _normalized_text(candidate.metric),
        "value_as_reported": _normalized_text(candidate.value_as_reported),
        "normalized_value": candidate.normalized_value,
        "unit_as_reported": (
            _normalized_text(candidate.unit_as_reported)
            if candidate.unit_as_reported else None
        ),
        "normalized_unit": (
            _normalized_text(candidate.normalized_unit)
            if candidate.normalized_unit else None
        ),
        "period": _normalized_text(candidate.period) if candidate.period else None,
        "geography": (
            _normalized_text(candidate.geography)
            if candidate.geography else None
        ),
        "crop": _normalized_text(candidate.crop) if candidate.crop else None,
        "scheme_name": (
            _normalized_text(candidate.scheme_name)
            if candidate.scheme_name else None
        ),
        "evidence_quote": candidate.evidence_quote.strip(),
        "evidence_validation": evidence_status,
        "normalization_status": _normalization_status(candidate),
        "review_status": "approved_for_write",
        "page_number": locator.page_number,
        "chunk_index": locator.chunk_index,
        "source_file": request.inspection.source_file,
        "source_url": locator.source_url,
        "source_hash": request.inspection.source_hash,
        "source_type": request.inspection.modality.value,
        "extraction_run_id": request.run_id,
        "extracting_agent": "semantic_document_fact_agent",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def _provenance(candidate, source_record, text_start, text_end):
    locator = source_record.record_locator.model_copy(update={
        "text_start": text_start,
        "text_end": text_end,
        "section_heading": heading_for_evidence(
            source_record.data.get("content", ""), text_start, text_end,
        ),
    })
    values: dict[str, Any] = {
        "fact_type": candidate.fact_type,
        "subject": candidate.subject,
        "metric": candidate.metric,
        "value_as_reported": candidate.value_as_reported,
        "normalized_value": candidate.normalized_value,
        "unit_as_reported": candidate.unit_as_reported,
        "normalized_unit": candidate.normalized_unit,
        "period": candidate.period,
        "geography": candidate.geography,
        "crop": candidate.crop,
        "scheme_name": candidate.scheme_name,
        "evidence_quote": candidate.evidence_quote,
        "normalization_status": _normalization_status(candidate),
    }
    return {
        field: FieldProvenance(
            locator=locator,
            raw_field="content",
            raw_value=value,
            transformation=(
                "deterministic_normalization_validation"
                if field == "normalization_status"
                else (
                    "model_proposed_normalization"
                    if field in {"normalized_value", "normalized_unit"}
                    else "evidence_anchored_semantic_extraction"
                )
            ),
            mapping_method="qwen_structured_fact_proposal",
            confidence=candidate.confidence,
        )
        for field, value in values.items()
        if value not in (None, "")
    }


class SemanticDocumentFactAgent:
    """Propose facts with a local model, then reject unsupported proposals."""

    def __init__(self, llm=None, model_name=None):
        self.llm = llm
        self.model_name = model_name or os.getenv("OLLAMA_MODEL", "qwen3:4b")

    def _model(self):
        if self.llm is not None:
            return self.llm
        from agent_config import get_chat_model

        return get_chat_model(temperature=0.0)

    def extract(self, request: ExtractSemanticFactsInput):
        if request.inspection.modality != SourceModality.PDF:
            raise ValueError("Semantic document fact extraction currently requires PDF input")

        available = [
            record for record in request.extraction.records
            if _normalized_text(record.data.get("content"))
        ]
        selected = available[:request.max_chunks]
        llm = self._model()
        candidates = []
        for start in range(0, len(selected), request.batch_size):
            batch = selected[start:start + request.batch_size]
            source_by_index = {record.record_index: record for record in batch}
            # Constrain generation, but retain invalid proposals for the audit below.
            schema = SemanticFactBatchProposal.model_json_schema()
            schema["$defs"]["SemanticFactCandidate"]["properties"][
                "source_record_index"
            ]["enum"] = sorted(source_by_index)
            structured = llm.with_structured_output(schema)
            prompt = {
                "task": (
                    "Extract only explicit numeric agricultural facts from the supplied "
                    "PDF chunks. Copy evidence_quote verbatim from one chunk. Never infer "
                    "a missing value, period, geography, crop, unit or scheme. Preserve "
                    "value_as_reported exactly. Copy period, geography, crop and scheme_name "
                    "verbatim when supplied; do not translate them. normalized_value and "
                    "normalized_unit are "
                    "optional model proposals. Return no fact when the evidence is "
                    "ambiguous. Use the provided source_record_index."
                ),
                "allowed_fact_types": [
                    "crop_area", "crop_production", "crop_yield",
                    "scheme_metric", "market_metric", "horticulture_metric",
                    "other_agriculture_metric",
                ],
                "maximum_facts": 8,
                "chunks": [
                    {
                        "source_record_index": record.record_index,
                        "page_number": record.record_locator.page_number,
                        "chunk_index": record.record_locator.chunk_index,
                        "content": record.data.get("content"),
                    }
                    for record in batch
                ],
            }
            proposal = structured.invoke(
                "You are a cautious evidence-grounded agricultural document fact "
                "extraction agent. Output only the requested schema.\n"
                + json.dumps(prompt, ensure_ascii=False, default=str)
            )
            if isinstance(proposal, SemanticFactBatchProposal):
                proposal = proposal.model_dump()
            envelope = _SemanticFactEnvelope.model_validate(proposal)
            candidates.extend(
                (candidate, source_by_index) for candidate in envelope.facts[:8]
            )

        mapped = []
        seen = set()
        duplicate_count = 0
        for raw_candidate, source_by_index in candidates:
            try:
                candidate = SemanticFactCandidate.model_validate(raw_candidate)
            except ValidationError as exc:
                # Do not retain or echo arbitrary model values in rejected records.
                error_types = sorted({error["type"] for error in exc.errors()})
                mapped.append(MappedRecord(
                    target_collection=TargetCollection.AGRICULTURE_FACTS,
                    data={},
                    field_provenance={},
                    mapping_confidence=0.0,
                    valid=False,
                    validation_errors=[
                        "Invalid fact structure: "
                        + str(exc.error_count()) + " error(s) ("
                        + ", ".join(error_types) + ")"
                    ],
                ))
                continue
            source_record = source_by_index.get(candidate.source_record_index)
            errors = []
            data = {}
            provenance = {}
            if source_record is None:
                errors.append("source_record_index is not present in the supplied batch")
            else:
                content = str(source_record.data.get("content") or "")
                evidence_status, text_start, text_end = _evidence_location(
                    content, candidate.evidence_quote
                )
                if evidence_status is None:
                    errors.append("evidence_quote is not present in the source chunk")
                if (
                    _normalized_text(candidate.value_as_reported)
                    not in _normalized_text(candidate.evidence_quote)
                ):
                    errors.append("value_as_reported is not present in evidence_quote")
                if (
                    candidate.unit_as_reported
                    and _normalized_text(candidate.unit_as_reported)
                    not in _normalized_text(candidate.evidence_quote)
                ):
                    errors.append("unit_as_reported is not present in evidence_quote")
                if not re.search(r"\d", candidate.value_as_reported):
                    errors.append("value_as_reported does not contain a numeric value")
                for field_name in (
                    "period", "geography", "crop", "scheme_name"
                ):
                    field_value = getattr(candidate, field_name)
                    if (
                        field_value
                        and _normalized_text(field_value)
                        not in _normalized_text(content)
                    ):
                        errors.append(
                            f"{field_name} is not present in the source chunk"
                        )
                if not errors:
                    data = _candidate_data(
                        candidate, request, source_record, evidence_status
                    )
                    if (
                        candidate.confidence < request.minimum_confidence
                        or data["normalization_status"]
                        == "model_proposed_requires_review"
                    ):
                        data["review_status"] = "human_review_required"
                    provenance = _provenance(
                        candidate, source_record, text_start, text_end
                    )
                    data["field_provenance"] = {
                        key: item.model_dump(mode="json")
                        for key, item in provenance.items()
                    }
                    data["model_evidence"] = {
                        "provider": "local_model",
                        "model_name": self.model_name,
                        "remote_api_used": False,
                        "validation": evidence_status,
                    }
                    try:
                        data = CanonicalAgricultureFact.model_validate(
                            data
                        ).model_dump(mode="json")
                    except (ValidationError, ValueError, TypeError) as exc:
                        errors.append(str(exc))
            # A rejected proposal must not hide a later grounded duplicate.
            if not errors:
                signature = _signature(candidate, request.inspection.source_hash)
                if signature in seen:
                    duplicate_count += 1
                    continue
                seen.add(signature)
            mapped.append(MappedRecord(
                target_collection=TargetCollection.AGRICULTURE_FACTS,
                data=data,
                field_provenance=provenance,
                mapping_confidence=candidate.confidence,
                valid=not errors,
                validation_errors=errors,
            ))

        valid = sum(record.valid for record in mapped)
        review_required = sum(
            record.valid
            and record.data.get("review_status") == "human_review_required"
            for record in mapped
        )
        return ExtractSemanticFactsOutput(
            records=mapped,
            chunks_available=len(available),
            chunks_examined=len(selected),
            facts_proposed=len(candidates),
            facts_valid=valid,
            facts_rejected=len(mapped) - valid,
            facts_review_required=review_required,
            duplicate_facts_removed=duplicate_count,
        )


def extract_semantic_pdf_facts(payload: ExtractSemanticFactsInput, llm=None):
    """Functional tool entry point used by the registry and LangChain adapter."""
    return SemanticDocumentFactAgent(llm=llm).extract(payload)
