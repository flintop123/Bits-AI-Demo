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
    FieldMapping,
    FieldProvenance,
    MappedRecord,
    MappingOutput,
    MappingPlan,
    MappingRequest,
    SeriesColumn,
    SeriesMapping,
    SourceModality,
    ReportingFrequency,
    TargetCollection,
)


PLANNER_FIELDS = {
    TargetCollection.AGRICULTURE_DOCUMENTS: [
        "document_title", "page_number", "chunk_index", "content",
        "language", "extraction_method", "source_type", "source_url",
        "source_file", "content_hash",
    ],
    TargetCollection.CROP_STATISTICS: [
        "crop", "season", "year", "area_hectares", "production",
        "yield_kg_per_hectare", "area_unit", "production_unit",
        "yield_unit", "source_file", "source_row",
    ],
    TargetCollection.MANDI_PRICES: [
        "district", "market", "date", "crop", "variety", "price",
        "minimum_price", "maximum_price", "unit", "arrival_quantity",
        "arrival_unit",
    ],
    TargetCollection.MANDI_LOCATIONS: [
        "market_code", "market_name", "district_code", "district_name",
        "location", "location_precision", "verification_status",
        "coordinate_source",
    ],
}


REQUIRED_SOURCE_FIELDS = {
    TargetCollection.AGRICULTURE_DOCUMENTS: [
        "document_title", "content", "language", "extraction_method",
    ],
    TargetCollection.CROP_STATISTICS: ["crop", "season", "year"],
    TargetCollection.MANDI_PRICES: [
        "district", "market", "date", "crop", "variety", "unit",
    ],
    TargetCollection.MANDI_LOCATIONS: [
        "market_code", "market_name", "district_code", "district_name",
        "location", "location_precision", "verification_status",
        "coordinate_source",
    ],
}


FIELD_TRANSFORMS = {
    "date": "date",
    "year": "year",
    "page_number": "integer",
    "chunk_index": "integer",
    "source_row": "integer",
    "market_code": "integer",
    "area_hectares": "number",
    "production": "number",
    "yield_kg_per_hectare": "number",
    "price": "number",
    "minimum_price": "number",
    "maximum_price": "number",
    "arrival_quantity": "number",
}


def _normalized_field_name(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _available_source_fields(request: MappingRequest):
    fields = []
    seen = set()
    for record in request.extraction.records:
        for source_field in record.data:
            if source_field not in seen:
                fields.append(source_field)
                seen.add(source_field)
    return fields


def _enforce_extractor_schema_contract(plan: MappingPlan, request: MappingRequest):
    """Reject a model target that conflicts with the extractor's record schema."""
    available = {
        _normalized_field_name(item) for item in _available_source_fields(request)
    }
    document_signature = {
        "documenttitle", "pagenumber", "chunkindex", "content", "language",
        "extractionmethod", "sourceurl", "sourcefile", "contenthash",
    }
    if (
        request.inspection.modality == SourceModality.PDF
        and document_signature.issubset(available)
        and plan.target_collection != TargetCollection.AGRICULTURE_DOCUMENTS
    ):
        original = plan.target_collection.value
        return plan.model_copy(update={
            "target_collection": TargetCollection.AGRICULTURE_DOCUMENTS,
            "source_scope": None,
            "data_start_row": None,
            "field_mappings": [],
            "series_mappings": [],
            "static_values": {},
            "identity_fields": [
                "source_url", "page_number", "chunk_index", "content_hash",
            ],
            "confidence": max(plan.confidence, 0.99),
            "explanation": (
                f"{plan.explanation} Extractor schema contract rejected "
                f"incompatible target {original}; canonical PDF chunks require "
                "agriculture_documents."
            ),
        })
    return plan


def _complete_exact_field_mappings(plan: MappingPlan, request: MappingRequest):
    """Restore unambiguous exact-name mappings omitted by the model.

    The language model still chooses the collection and semantic mappings. This
    safeguard only accepts a source key whose normalized spelling exactly equals
    a canonical field, so it cannot invent a synonym or value.
    """
    available = {}
    for record in request.extraction.records:
        for source_field in record.data:
            available.setdefault(_normalized_field_name(source_field), source_field)

    mapped_targets = {item.target_field for item in plan.field_mappings}
    static_targets = set(plan.static_values)
    additions = []
    for target_field in PLANNER_FIELDS[plan.target_collection]:
        if target_field in mapped_targets or target_field in static_targets:
            continue
        source_field = available.get(_normalized_field_name(target_field))
        if source_field is None:
            continue
        additions.append(FieldMapping(
            source_field=source_field,
            target_field=target_field,
            transformation=FIELD_TRANSFORMS.get(target_field, "identity"),
            mapping_method="exact_name_schema_safeguard",
        ))

    if not additions:
        return plan
    restored = ", ".join(item.target_field for item in additions)
    return plan.model_copy(update={
        "field_mappings": [*plan.field_mappings, *additions],
        "explanation": (
            f"{plan.explanation} Exact-name schema safeguard restored: {restored}."
        ),
    })


WIDE_MEASURE_PATTERNS = (
    ("yield_kg_per_hectare", re.compile(r"\byield\b", re.IGNORECASE)),
    ("production", re.compile(r"\bproduction\b", re.IGNORECASE)),
    ("area_hectares", re.compile(r"\barea\b", re.IGNORECASE)),
)


def _period_from_header(value):
    match = re.search(r"\b(20\d{2}-\d{2})\b", str(value or ""))
    return match.group(1) if match else None


def _measure_from_header(value):
    text = str(value or "")
    for target_field, pattern in WIDE_MEASURE_PATTERNS:
        if pattern.search(text):
            return target_field
    return None


def _wide_header_candidate(request: MappingRequest):
    best = None
    for record in request.extraction.records:
        columns = []
        for source_field, value in record.data.items():
            period = _period_from_header(value)
            measure = _measure_from_header(value)
            if period and measure:
                columns.append((measure, period, source_field))
        if len(columns) < 2:
            continue
        periods = {item[1] for item in columns}
        measures = {item[0] for item in columns}
        score = (len(columns), len(periods), len(measures))
        if best is None or score > best[0]:
            best = (score, record, columns)
    return best


def _header_direct_mapping(record, target_field):
    expected = _normalized_field_name(target_field)
    for source_field, value in record.data.items():
        normalized = _normalized_field_name(value)
        if normalized == expected:
            return source_field
    return None


def _repair_wide_crop_statistics_plan(plan: MappingPlan, request: MappingRequest):
    """Convert an evident wide crop-statistics header into period mappings.

    This repair is intentionally bounded to Excel crop-statistics plans and
    requires explicit measure names and reporting periods in one source row.
    """
    if (
        request.inspection.modality != SourceModality.EXCEL
        or plan.target_collection != TargetCollection.CROP_STATISTICS
    ):
        return plan
    candidate = _wide_header_candidate(request)
    if candidate is None:
        return plan

    _score, header_record, columns = candidate
    detected_series = []
    for target_field, _pattern in WIDE_MEASURE_PATTERNS:
        series_columns = [
            SeriesColumn(period=period, source_field=source_field)
            for measure, period, source_field in columns
            if measure == target_field
        ]
        if series_columns:
            detected_series.append(SeriesMapping(
                target_field=target_field,
                columns=series_columns,
                transformation="number",
                mapping_method="wide_header_schema_safeguard",
            ))

    detected_count = sum(len(item.columns) for item in detected_series)
    existing_count = sum(len(item.columns) for item in plan.series_mappings)
    updates = {}
    repaired = []
    if detected_count > existing_count:
        updates["series_mappings"] = detected_series
        repaired.append(f"{detected_count} period-measure columns")

    header_row = header_record.record_locator.row_number
    if header_row and (
        plan.data_start_row is None or plan.data_start_row <= header_row
    ):
        updates["data_start_row"] = header_row + 1
        repaired.append(f"data row {header_row + 1}")
    if not plan.source_scope and header_record.record_locator.sheet_name:
        updates["source_scope"] = header_record.record_locator.sheet_name
        repaired.append(f"sheet {header_record.record_locator.sheet_name}")

    field_mappings = list(plan.field_mappings)
    mapped_targets = {item.target_field for item in field_mappings}
    for target_field in ("crop", "season"):
        if target_field in mapped_targets:
            continue
        source_field = _header_direct_mapping(header_record, target_field)
        if source_field:
            field_mappings.append(FieldMapping(
                source_field=source_field,
                target_field=target_field,
                transformation="text",
                mapping_method="wide_header_schema_safeguard",
            ))
            repaired.append(f"{source_field} to {target_field}")
    if len(field_mappings) != len(plan.field_mappings):
        updates["field_mappings"] = field_mappings

    identity_fields = list(plan.identity_fields)
    for field in ("crop", "season", "year"):
        if field not in identity_fields:
            identity_fields.append(field)
    if identity_fields != plan.identity_fields:
        updates["identity_fields"] = identity_fields

    if not updates:
        return plan
    updates["explanation"] = (
        f"{plan.explanation} Wide-header schema safeguard restored: "
        f"{', '.join(repaired)}."
    )
    return plan.model_copy(update=updates)


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
        for record in request.extraction.records[:5]:
            preview.append({
                "record_index": record.record_index,
                "locator": record.record_locator.model_dump(mode="json"),
                "data": record.data,
            })
        available_source_fields = _available_source_fields(request)
        prompt = {
            "task": (
                "Propose one safe mapping from the extracted source into exactly one "
                "allowed canonical collection. Do not write data and do not invent values. "
                "Use source column letters/keys exactly as shown. Map every required "
                "source field when it is present. For wide annual Excel "
                "tables use series_mappings to map each period column. Set data_start_row "
                "to the first actual data row. Select a structured collection only when "
                "the extracted source fields contain evidence for its required schema. "
                "Classify the source reporting_frequency as daily, weekly, monthly, "
                "annual, event or unknown. Supply reporting period start and end dates "
                "when the source explicitly states a bounded reporting window. "
                "Explain uncertainty."
            ),
            "allowed_collections": [item.value for item in request.allowed_collections],
            "canonical_fields": {
                key.value: value for key, value in PLANNER_FIELDS.items()
            },
            "required_source_fields": {
                key.value: value for key, value in REQUIRED_SOURCE_FIELDS.items()
            },
            "source": request.inspection.model_dump(mode="json"),
            "extraction_method": request.extraction.extraction_method,
            "available_source_fields": available_source_fields,
            "preview": preview,
        }
        structured = llm.with_structured_output(MappingPlan)
        plan = structured.invoke(
            "You are a cautious agricultural data schema-mapping agent.\n"
            + json.dumps(prompt, ensure_ascii=False, default=str)
        )
        if plan.target_collection not in request.allowed_collections:
            raise ValueError("The mapping agent selected a non-allowlisted collection")
        plan = _enforce_extractor_schema_contract(plan, request)
        plan = _complete_exact_field_mappings(plan, request)
        return _repair_wide_crop_statistics_plan(plan, request)


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
            mapping_method=mapping.mapping_method,
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


def _temporal_metadata(data, provenance, plan, record):
    frequency = plan.reporting_frequency
    period_start = plan.reporting_period_start
    period_end = plan.reporting_period_end
    method = "model_proposed_reporting_period"

    if frequency == ReportingFrequency.UNKNOWN and data.get("date"):
        frequency = ReportingFrequency.DAILY
        period_start = period_end = data["date"]
        method = "canonical_date_schema_safeguard"
    elif frequency == ReportingFrequency.UNKNOWN and data.get("year"):
        frequency = ReportingFrequency.ANNUAL
        start_year = int(data["year"][:4])
        period_start = f"{start_year:04d}-04-01"
        period_end = f"{start_year + 1:04d}-03-31"
        method = "canonical_year_schema_safeguard"

    data["reporting_frequency"] = frequency.value
    if period_start and period_end:
        data["reporting_period_start"] = period_start
        data["reporting_period_end"] = period_end
    provenance["reporting_frequency"] = FieldProvenance(
        locator=record.record_locator,
        raw_field=None,
        raw_value=frequency.value,
        transformation="temporal_classification",
        mapping_method=method,
        confidence=plan.confidence,
    )


def _augment_record(data, provenance, request, record, plan):
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
    _temporal_metadata(data, provenance, plan, record)
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
                period_methods = {
                    series.mapping_method
                    for series in plan.series_mappings
                    if any(item.period == period for item in series.columns)
                }
                provenance["year"] = FieldProvenance(
                    locator=record.record_locator,
                    raw_value=period,
                    transformation="wide_period_header",
                    mapping_method=(
                        "wide_header_schema_safeguard"
                        if "wide_header_schema_safeguard" in period_methods
                        else "model_proposed_series_mapping"
                    ),
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
                        mapping_method=series.mapping_method,
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
            _augment_record(data, provenance, request, record, plan)
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
