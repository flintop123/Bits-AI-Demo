"""Model-assisted mapping followed by deterministic schema validation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ingestion_v2.models import (
    ExtractedRecord,
    FieldProvenance,
    MappedRecord,
    MappingOutput,
    MappingPlan,
    MappingRequest,
    SourceModality,
    TargetCollection,
)


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class CanonicalDocument(CanonicalModel):
    document_title: str
    page_number: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    language: str
    extraction_method: str
    source_type: str
    source_url: str
    source_file: str
    content_hash: str


class CanonicalCropStatistic(CanonicalModel):
    crop: str = Field(min_length=1)
    season: str = Field(min_length=1)
    year: str = Field(pattern=r"^\d{4}-\d{2}$")
    area_hectares: float | None = Field(default=None, ge=0)
    production: float | None = Field(default=None, ge=0)
    yield_kg_per_hectare: float | None = Field(default=None, ge=0)
    area_unit: str = "hectare"
    production_unit: str = "tonne"
    yield_unit: str = "kg_per_hectare"
    source_file: str
    source_row: int = Field(ge=1)

    @model_validator(mode="after")
    def require_measure(self):
        if all(
            value is None
            for value in (
                self.area_hectares,
                self.production,
                self.yield_kg_per_hectare,
            )
        ):
            raise ValueError("at least one crop-statistics measure is required")
        return self


class CanonicalMandiPrice(CanonicalModel):
    source_record_id: str
    district: str = Field(min_length=1)
    market: str = Field(min_length=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    crop: str = Field(min_length=1)
    variety: str = Field(min_length=1)
    price: float | None = Field(default=None, ge=0)
    minimum_price: float | None = Field(default=None, ge=0)
    maximum_price: float | None = Field(default=None, ge=0)
    unit: str
    source_url: str


class CanonicalMandiLocation(CanonicalModel):
    market_code: int
    market_name: str = Field(min_length=1)
    district_code: str
    district_name: str = Field(min_length=1)
    location: dict[str, Any]
    location_precision: str
    verification_status: str
    coordinate_source: str

    @model_validator(mode="after")
    def require_verified_geojson(self):
        if self.verification_status != "verified":
            raise ValueError("only verified locations may be persisted")
        if self.location_precision not in {
            "market_facility", "market_locality_centroid"
        }:
            raise ValueError("unsupported location precision")
        if self.location.get("type") != "Point":
            raise ValueError("location must be a GeoJSON Point")
        coordinates = self.location.get("coordinates", [])
        if len(coordinates) != 2:
            raise ValueError("GeoJSON Point requires longitude and latitude")
        return self


CANONICAL_MODELS = {
    TargetCollection.AGRICULTURE_DOCUMENTS: CanonicalDocument,
    TargetCollection.CROP_STATISTICS: CanonicalCropStatistic,
    TargetCollection.MANDI_PRICES: CanonicalMandiPrice,
    TargetCollection.MANDI_LOCATIONS: CanonicalMandiLocation,
}


class SchemaMappingAgent:
    """Ask a bounded chat model for a mapping plan, never for DB commands."""

    def __init__(self, llm=None):
        self.llm = llm

    def propose(self, request: MappingRequest):
        llm = self.llm
        if llm is None:
            from agent_config import get_chat_model
            llm = get_chat_model(temperature=0.0)

        preview = []
        for record in request.extraction.records[:16]:
            preview.append({
                "record_index": record.record_index,
                "locator": record.record_locator.model_dump(mode="json"),
                "data": record.data,
            })
        prompt = {
            "task": (
                "Propose one safe mapping from the extracted source into exactly one "
                "allowed canonical collection. Do not write data and do not invent values. "
                "Use source column letters/keys exactly as shown. For wide annual Excel "
                "tables use series_mappings to map each period column. Set data_start_row "
                "to the first actual data row. Explain uncertainty."
            ),
            "allowed_collections": [item.value for item in request.allowed_collections],
            "canonical_fields": {
                "agriculture_documents": [
                    "document_title", "page_number", "chunk_index", "content",
                    "language", "extraction_method", "source_type", "source_url",
                    "source_file", "content_hash",
                ],
                "crop_statistics": [
                    "crop", "season", "year", "area_hectares", "production",
                    "yield_kg_per_hectare", "area_unit", "production_unit",
                    "yield_unit", "source_file", "source_row",
                ],
                "mandi_prices": [
                    "district", "market", "date", "crop", "variety", "price",
                    "minimum_price", "maximum_price", "unit", "arrival_quantity",
                    "arrival_unit",
                ],
            },
            "source": request.inspection.model_dump(mode="json"),
            "extraction_method": request.extraction.extraction_method,
            "preview": preview,
        }
        structured = llm.with_structured_output(MappingPlan)
        plan = structured.invoke(
            "You are a cautious agricultural data schema-mapping agent.\n"
            + json.dumps(prompt, ensure_ascii=False, default=str)
        )
        if plan.target_collection not in request.allowed_collections:
            raise ValueError("The mapping agent selected a non-allowlisted collection")
        return plan


def _text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _number(value):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, str):
        value = value.replace(",", "").strip()
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            raise ValueError(f"not a numeric value: {value}")
        value = match.group(0)
    return float(value)


def _date(value):
    text = _text(value)
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"unsupported date: {text}")


def _year(value):
    text = _text(value)
    match = re.search(r"\b\d{4}-\d{2}\b", text)
    if not match:
        raise ValueError(f"unsupported reporting year: {text}")
    return match.group(0)


TRANSFORMS = {
    "identity": lambda value: value,
    "text": _text,
    "number": _number,
    "integer": lambda value: int(_number(value)),
    "date": _date,
    "year": _year,
}


def _in_scope(record: ExtractedRecord, plan: MappingPlan):
    locator = record.record_locator
    if plan.source_scope and locator.sheet_name != plan.source_scope:
        return False
    if plan.data_start_row and (
        locator.row_number is None or locator.row_number < plan.data_start_row
    ):
        return False
    return True


def _base_data(record, plan):
    data = dict(plan.static_values)
    provenance = {}
    for mapping in plan.field_mappings:
        if mapping.source_field not in record.data:
            continue
        raw_value = record.data.get(mapping.source_field)
        if raw_value is None or str(raw_value).strip() == "":
            continue
        value = TRANSFORMS[mapping.transformation](raw_value)
        data[mapping.target_field] = value
        if mapping.unit:
            data[f"{mapping.target_field}_unit"] = mapping.unit
        provenance[mapping.target_field] = FieldProvenance(
            locator=record.field_locators.get(
                mapping.source_field, record.record_locator
            ),
            raw_field=mapping.source_field,
            raw_value=raw_value,
            transformation=mapping.transformation,
            mapping_method="model_proposed_schema_mapping",
            confidence=plan.confidence,
        )
    for key, value in plan.static_values.items():
        provenance[key] = FieldProvenance(
            locator=record.record_locator,
            raw_field=None,
            raw_value=value,
            transformation="static_validated_value",
            mapping_method="mapping_plan_static_value",
            confidence=plan.confidence,
        )
    return data, provenance


def _augment_record(data, provenance, request, record):
    locator = record.record_locator
    data.setdefault("source_file", request.inspection.source_file)
    data.setdefault("source_url", locator.source_url or PathLike.file_uri(
        request.inspection.file_path
    ))
    if locator.row_number:
        data.setdefault("source_row", locator.row_number)
    data.update({
        "extraction_run_id": request.run_id,
        "extracting_agent": "agentic_schema_mapping_agent",
        "source_type": request.inspection.modality.value,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "source_hash": request.inspection.source_hash,
    })
    if request.inspection.modality == SourceModality.PDF:
        data.setdefault("page_number", locator.page_number)
        data.setdefault("chunk_index", locator.chunk_index)
    if "content" in data and not data.get("content_hash"):
        identity = f"{data.get('source_url')}|{data.get('page_number')}|{data.get('chunk_index')}|{data['content']}"
        data["content_hash"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    if data.get("year") == "2024-25":
        data.setdefault("is_advance_estimate", True)
    data["field_provenance"] = {
        key: item.model_dump(mode="json") for key, item in provenance.items()
    }


class PathLike:
    @staticmethod
    def file_uri(path):
        from pathlib import Path
        return Path(path).resolve().as_uri()


def _canonicalize(target, data):
    model = CANONICAL_MODELS.get(target)
    if model is None:
        raise ValueError(f"No canonical validator is registered for {target.value}")
    return model.model_validate(data).model_dump(mode="json")


def _periods(plan):
    periods = []
    for series in plan.series_mappings:
        for column in series.columns:
            if column.period not in periods:
                periods.append(column.period)
    return periods


def apply_mapping_plan(request: MappingRequest, plan: MappingPlan):
    mapped = []
    periods = _periods(plan)
    required_total = 0
    required_present = 0

    for record in request.extraction.records:
        if not _in_scope(record, plan):
            continue
        base_data, base_provenance = _base_data(record, plan)
        variants = [(None, base_data, base_provenance)]
        if periods:
            variants = []
            for period in periods:
                data = dict(base_data)
                provenance = dict(base_provenance)
                data["year"] = period
                provenance["year"] = FieldProvenance(
                    locator=record.record_locator,
                    raw_value=period,
                    transformation="wide_period_header",
                    mapping_method="model_proposed_series_mapping",
                    confidence=plan.confidence,
                )
                for series in plan.series_mappings:
                    column = next(
                        (item for item in series.columns if item.period == period),
                        None,
                    )
                    if column is None:
                        continue
                    raw_value = record.data.get(column.source_field)
                    if raw_value is None or str(raw_value).strip() == "":
                        continue
                    data[series.target_field] = TRANSFORMS[
                        series.transformation
                    ](raw_value)
                    provenance[series.target_field] = FieldProvenance(
                        locator=record.field_locators.get(
                            column.source_field, record.record_locator
                        ),
                        raw_field=column.source_field,
                        raw_value=raw_value,
                        transformation=series.transformation,
                        mapping_method="model_proposed_series_mapping",
                        confidence=plan.confidence,
                    )
                variants.append((period, data, provenance))

        for _period, data, provenance in variants:
            if plan.target_collection == TargetCollection.MANDI_PRICES:
                identity = (
                    f"{request.inspection.source_hash}|"
                    f"{record.record_locator.json_path or record.record_index}"
                )
                data.setdefault(
                    "source_record_id",
                    hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                )
            _augment_record(data, provenance, request, record)
            errors = []
            try:
                data = _canonicalize(plan.target_collection, data)
            except (ValidationError, ValueError, TypeError) as exc:
                errors.append(str(exc))
            required = plan.identity_fields
            required_total += len(required)
            required_present += sum(
                1 for field in required if data.get(field) not in (None, "")
            )
            mapped.append(MappedRecord(
                target_collection=plan.target_collection,
                data=data,
                field_provenance=provenance,
                mapping_confidence=plan.confidence,
                valid=not errors,
                validation_errors=errors,
            ))

    valid_count = sum(item.valid for item in mapped)
    attempted = len(mapped)
    return MappingOutput(
        plan=plan,
        records=mapped,
        records_attempted=attempted,
        records_valid=valid_count,
        records_rejected=attempted - valid_count,
        required_field_coverage=(
            required_present / required_total if required_total else 0
        ),
        validation_rate=(valid_count / attempted if attempted else 0),
    )
