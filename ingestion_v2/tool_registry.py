"""Versioned machine-readable contracts for all ingestion-v2 tools."""

from ingestion_v2.models import (
    ExtractFileInput,
    ExtractFileOutput,
    InspectFileInput,
    InspectFileOutput,
    MappingOutput,
    MappingRequest,
    PersistInput,
    PersistOutput,
    TargetCollection,
    ToolContract,
)


def _contract(
    name,
    version,
    description,
    input_model,
    output_model,
    *,
    side_effect="none",
    allowed_collections=(),
    idempotent=True,
    dry_run_supported=False,
):
    return ToolContract(
        name=name,
        version=version,
        description=description,
        input_schema=input_model.model_json_schema(),
        output_schema=output_model.model_json_schema(),
        side_effect=side_effect,
        allowed_collections=list(allowed_collections),
        idempotent=idempotent,
        dry_run_supported=dry_run_supported,
    )


TOOL_CONTRACTS = {
    "inspect_input_file": _contract(
        "inspect_input_file",
        "2.0.0",
        "Inspect a supported input and return its immutable identity and modality.",
        InspectFileInput,
        InspectFileOutput,
        side_effect="read",
    ),
    "extract_supported_file": _contract(
        "extract_supported_file",
        "2.0.0",
        "Extract PDF, Excel, CSV or JSON records with source locators.",
        ExtractFileInput,
        ExtractFileOutput,
        side_effect="read",
    ),
    "propose_and_apply_mapping": _contract(
        "propose_and_apply_mapping",
        "2.0.0",
        "Use a bounded language model to propose a canonical mapping and validate its output.",
        MappingRequest,
        MappingOutput,
        side_effect="none",
        allowed_collections=(
            TargetCollection.AGRICULTURE_DOCUMENTS,
            TargetCollection.CROP_STATISTICS,
            TargetCollection.MANDI_PRICES,
            TargetCollection.MANDI_LOCATIONS,
        ),
    ),
    "persist_validated_records": _contract(
        "persist_validated_records",
        "2.0.0",
        "Upsert only schema-valid records into one allowlisted MongoDB collection.",
        PersistInput,
        PersistOutput,
        side_effect="write",
        allowed_collections=(
            TargetCollection.AGRICULTURE_DOCUMENTS,
            TargetCollection.CROP_STATISTICS,
            TargetCollection.MANDI_PRICES,
            TargetCollection.MANDI_LOCATIONS,
        ),
        dry_run_supported=True,
    ),
}


def tool_contracts_document():
    return {
        name: contract.model_dump(mode="json")
        for name, contract in TOOL_CONTRACTS.items()
    }
