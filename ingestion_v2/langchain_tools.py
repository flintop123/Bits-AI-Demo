"""LangChain StructuredTool adapters for the ingestion-v2 contracts.

These tools are not added to the existing Rishi ReAct agent.  A later,
separately reviewed agent can import ``default_ingestion_tools``.
"""

from langchain_core.tools import tool

from ingestion_v2.extraction import (
    extract_supported_file as _extract_supported_file,
    inspect_input_file as _inspect_input_file,
)
from ingestion_v2.evidence_report import (
    compare_run_evidence as _compare_run_evidence,
    write_run_evidence_report as _write_run_evidence_report,
)
from ingestion_v2.mapping import SchemaMappingAgent, apply_mapping_plan
from ingestion_v2.models import (
    BuildEvidenceReportInput,
    CompareEvidenceRunsInput,
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


@tool("build_ingestion_evidence_report_v2", args_schema=BuildEvidenceReportInput)
def build_ingestion_evidence_report_v2(
    run_directory: str,
    verify_mongo: bool = False,
    max_records: int = 100,
) -> dict:
    """Generate auditable source, mapping, validation and Mongo evidence."""
    result = _write_run_evidence_report(
        run_directory,
        verify_mongo=verify_mongo,
        max_records=max_records,
    )
    report = result["report"]
    return {
        "run_id": report["run"].get("run_id"),
        "json_path": str(result["json"]),
        "html_path": str(result["html"]),
        "mongo_status": report["mongo_verification"]["status"],
        "records_in_report": report["records_in_report"],
    }


@tool("compare_ingestion_runs_v2", args_schema=CompareEvidenceRunsInput)
def compare_ingestion_runs_v2(
    before_run_directory: str,
    after_run_directory: str,
    output_directory: str,
) -> dict:
    """Compare failed and corrected ingestion outcomes quantitatively."""
    result = _compare_run_evidence(
        before_run_directory,
        after_run_directory,
        output_directory,
    )
    comparison = result["comparison"]
    return {
        "before_run_id": comparison["before"]["run_id"],
        "after_run_id": comparison["after"]["run_id"],
        "json_path": str(result["json"]),
        "html_path": str(result["html"]),
        "conclusion": comparison["conclusion"],
    }


def default_ingestion_tools():
    return [
        inspect_input_file_v2,
        extract_supported_file_v2,
        propose_and_apply_mapping_v2,
        persist_validated_records_v2,
        build_ingestion_evidence_report_v2,
        compare_ingestion_runs_v2,
    ]
