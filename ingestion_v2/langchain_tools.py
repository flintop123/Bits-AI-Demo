"""LangChain StructuredTool adapters for the ingestion-v2 contracts.

These tools are not added to the existing Rishi ReAct agent.  A later,
separately reviewed agent can import ``default_ingestion_tools``.
"""

from langchain_core.tools import tool

from ingestion_v2.extraction import (
    extract_supported_file as _extract_supported_file,
    inspect_input_file as _inspect_input_file,
)
from ingestion_v2.mapping import SchemaMappingAgent, apply_mapping_plan
from ingestion_v2.models import (
    ExtractFileInput,
    InspectFileInput,
    MappingRequest,
    PersistInput,
)
from ingestion_v2.persistence import (
    persist_validated_records as _persist_validated_records,
)


@tool("inspect_input_file_v2", args_schema=InspectFileInput)
def inspect_input_file_v2(file_path: str) -> dict:
    """Inspect a local PDF, Excel, CSV or JSON input without modifying it."""
    return _inspect_input_file(
        InspectFileInput(file_path=file_path)
    ).model_dump(mode="json")


@tool("extract_supported_file_v2", args_schema=ExtractFileInput)
def extract_supported_file_v2(
    file_path: str,
    force_ocr: bool = False,
    languages: list[str] | None = None,
) -> dict:
    """Extract candidate records and exact source locators from a supported file."""
    payload = ExtractFileInput(
        file_path=file_path,
        force_ocr=force_ocr,
        languages=languages or ["hin", "eng"],
    )
    return _extract_supported_file(payload).model_dump(mode="json")


@tool("propose_and_apply_mapping_v2", args_schema=MappingRequest)
def propose_and_apply_mapping_v2(
    run_id: str,
    inspection: dict,
    extraction: dict,
    allowed_collections: list | None = None,
) -> dict:
    """Propose a canonical schema mapping, apply it, and validate every record."""
    values = {
        "run_id": run_id,
        "inspection": inspection,
        "extraction": extraction,
    }
    if allowed_collections is not None:
        values["allowed_collections"] = allowed_collections
    request = MappingRequest.model_validate(values)
    plan = SchemaMappingAgent().propose(request)
    return apply_mapping_plan(request, plan).model_dump(mode="json")


@tool("persist_validated_records_v2", args_schema=PersistInput)
def persist_validated_records_v2(
    run_id: str,
    records: list[dict],
    write_mode: str = "dry_run",
    minimum_confidence: float = 0.85,
) -> dict:
    """Dry-run or upsert only validated, high-confidence canonical records."""
    payload = PersistInput.model_validate({
        "run_id": run_id,
        "records": records,
        "write_mode": write_mode,
        "minimum_confidence": minimum_confidence,
    })
    return _persist_validated_records(payload).model_dump(mode="json")


def default_ingestion_tools():
    return [
        inspect_input_file_v2,
        extract_supported_file_v2,
        propose_and_apply_mapping_v2,
        persist_validated_records_v2,
    ]
