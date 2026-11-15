"""Pydantic contracts shared by every ingestion-v2 tool and stage."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceModality(str, Enum):
    PDF = "pdf"
    EXCEL = "excel"
    CSV = "csv"
    JSON = "json"


class TargetCollection(str, Enum):
    AGRICULTURE_DOCUMENTS = "agriculture_documents"
    CROP_STATISTICS = "crop_statistics"
    MANDI_PRICES = "mandi_prices"
    MANDI_LOCATIONS = "mandi_locations"
    QUARANTINE = "ingestion_quarantine"


class RunStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class StageStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class WriteMode(str, Enum):
    DRY_RUN = "dry_run"
    WRITE = "write"


class SourceLocator(StrictModel):
    source_file: str
    source_url: str | None = None
    modality: SourceModality
    page_number: int | None = Field(default=None, ge=1)
    chunk_index: int | None = Field(default=None, ge=0)
    section_heading: str | None = None
    text_start: int | None = Field(default=None, ge=0)
    text_end: int | None = Field(default=None, ge=0)
    bounding_box: list[float] | None = None
    sheet_name: str | None = None
    row_number: int | None = Field(default=None, ge=1)
    column_name: str | None = None
    cell_reference: str | None = None
    json_path: str | None = None

    @field_validator("bounding_box")
    @classmethod
    def validate_bounding_box(cls, value):
        if value is not None and len(value) != 4:
            raise ValueError("bounding_box must contain [x0, y0, x1, y1]")
        return value


class FieldProvenance(StrictModel):
    locator: SourceLocator
    raw_field: str | None = None
    raw_value: Any = None
    transformation: str = "identity"
    mapping_method: str
    confidence: float = Field(ge=0, le=1)


class InspectFileInput(StrictModel):
    file_path: str


class InspectFileOutput(StrictModel):
    file_path: str
    source_file: str
    source_hash: str
    size_bytes: int = Field(ge=0)
    modality: SourceModality
    mime_type: str
    supported: bool


class ExtractFileInput(StrictModel):
    file_path: str
    force_ocr: bool = False
    languages: list[str] = Field(default_factory=lambda: ["hin", "eng"])


class ExtractedRecord(StrictModel):
    record_index: int = Field(ge=0)
    data: dict[str, Any]
    field_locators: dict[str, SourceLocator]
    record_locator: SourceLocator


class ExtractionMetrics(StrictModel):
    source_units_attempted: int = Field(ge=0)
    source_units_extracted: int = Field(ge=0)
    records_extracted: int = Field(ge=0)
    units_skipped: int = Field(ge=0)
    extraction_coverage: float = Field(ge=0, le=1)


class ExtractFileOutput(StrictModel):
    modality: SourceModality
    extraction_method: str
    records: list[ExtractedRecord]
    metrics: ExtractionMetrics
    warnings: list[str] = Field(default_factory=list)


class FieldMapping(StrictModel):
    source_field: str
    target_field: str
    transformation: Literal[
        "identity", "text", "number", "integer", "date", "year"
    ] = "identity"
    unit: str | None = None
    mapping_method: Literal[
        "model_proposed_schema_mapping",
        "exact_name_schema_safeguard",
        "wide_header_schema_safeguard",
    ] = "model_proposed_schema_mapping"


class SeriesColumn(StrictModel):
    period: str
    source_field: str


class SeriesMapping(StrictModel):
    target_field: str
    columns: list[SeriesColumn]
    transformation: Literal["number", "integer"] = "number"
    unit: str | None = None
    mapping_method: Literal[
        "model_proposed_series_mapping",
        "wide_header_schema_safeguard",
    ] = "model_proposed_series_mapping"


class MappingPlan(StrictModel):
    target_collection: TargetCollection
    source_scope: str | None = Field(
        default=None,
        description="Worksheet name or JSON record path selected by the agent",
    )
    data_start_row: int | None = Field(default=None, ge=1)
    field_mappings: list[FieldMapping]
    series_mappings: list[SeriesMapping] = Field(default_factory=list)
    static_values: dict[str, Any] = Field(default_factory=dict)
    identity_fields: list[str]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class MappingRequest(StrictModel):
    run_id: str
    inspection: InspectFileOutput
    extraction: ExtractFileOutput
    allowed_collections: list[TargetCollection] = Field(
        default_factory=lambda: [
            TargetCollection.AGRICULTURE_DOCUMENTS,
            TargetCollection.CROP_STATISTICS,
            TargetCollection.MANDI_PRICES,
            TargetCollection.MANDI_LOCATIONS,
        ]
    )


class MappedRecord(StrictModel):
    target_collection: TargetCollection
    data: dict[str, Any]
    field_provenance: dict[str, FieldProvenance]
    mapping_confidence: float = Field(ge=0, le=1)
    valid: bool
    validation_errors: list[str] = Field(default_factory=list)


class MappingOutput(StrictModel):
    plan: MappingPlan
    records: list[MappedRecord]
    records_attempted: int = Field(ge=0)
    records_valid: int = Field(ge=0)
    records_rejected: int = Field(ge=0)
    required_field_coverage: float = Field(ge=0, le=1)
    validation_rate: float = Field(ge=0, le=1)


class PersistInput(StrictModel):
    run_id: str
    write_mode: WriteMode = WriteMode.DRY_RUN
    minimum_confidence: float = Field(default=0.85, ge=0, le=1)
    records: list[MappedRecord]


class PersistOutput(StrictModel):
    write_mode: WriteMode
    target_collection: TargetCollection
    attempted: int = Field(ge=0)
    eligible: int = Field(ge=0)
    inserted: int = Field(ge=0)
    matched: int = Field(ge=0)
    modified: int = Field(ge=0)
    rejected: int = Field(ge=0)
    quarantined: int = Field(ge=0)
    document_ids: list[str] = Field(default_factory=list)


class BuildEvidenceReportInput(StrictModel):
    run_directory: str
    verify_mongo: bool = False
    max_records: int = Field(default=100, ge=1, le=1000)


class BuildEvidenceReportOutput(StrictModel):
    run_id: str
    json_path: str
    html_path: str
    mongo_status: str
    records_in_report: int = Field(ge=0)


class CompareEvidenceRunsInput(StrictModel):
    before_run_directory: str
    after_run_directory: str
    output_directory: str


class CompareEvidenceRunsOutput(StrictModel):
    before_run_id: str
    after_run_id: str
    json_path: str
    html_path: str
    conclusion: str


class RunEvent(StrictModel):
    sequence: int = Field(ge=1)
    timestamp: str = Field(default_factory=utc_now)
    stage: str
    status: StageStatus
    tool_name: str | None = None
    tool_version: str | None = None
    message: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None


class RunMetrics(StrictModel):
    source_units_attempted: int = 0
    source_units_extracted: int = 0
    candidate_records: int = 0
    valid_records: int = 0
    rejected_records: int = 0
    inserted: int = 0
    matched: int = 0
    modified: int = 0
    extraction_coverage: float = 0
    required_field_coverage: float = 0
    validation_rate: float = 0
    persistence_rate: float = 0


class IngestionRun(StrictModel):
    run_id: str
    status: RunStatus
    started_at: str = Field(default_factory=utc_now)
    completed_at: str | None = None
    source: InspectFileOutput | None = None
    target_collection: TargetCollection | None = None
    agent_id: str = "agentic_ingestion_v2"
    model: str | None = None
    mapping_plan: MappingPlan | None = None
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    events: list[RunEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    write_mode: WriteMode = WriteMode.DRY_RUN


class ToolContract(StrictModel):
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    side_effect: Literal["none", "read", "write"]
    allowed_collections: list[TargetCollection] = Field(default_factory=list)
    idempotent: bool
    dry_run_supported: bool
