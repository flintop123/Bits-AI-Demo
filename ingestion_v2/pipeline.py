"""Independent ingestion-v2 pipeline; does not modify the existing ReAct layer."""

from __future__ import annotations

import uuid

from ingestion_v2.extraction import extract_supported_file, inspect_input_file
from ingestion_v2.mapping import SchemaMappingAgent, apply_mapping_plan
from ingestion_v2.models import (
    ExtractFileInput,
    IngestionRun,
    InspectFileInput,
    MappingRequest,
    PersistInput,
    RunMetrics,
    RunStatus,
    WriteMode,
    utc_now,
)
from ingestion_v2.persistence import persist_validated_records
from ingestion_v2.run_store import LocalIngestionRunStore


class AgenticIngestionPipeline:
    def __init__(self, planner=None, store=None, database=None):
        self.planner = planner or SchemaMappingAgent()
        self.store = store or LocalIngestionRunStore()
        self.database = database

    def run(self, file_path, *, write=False, force_ocr=False, plan=None):
        run = IngestionRun(
            run_id=str(uuid.uuid4()),
            status=RunStatus.STARTED,
            write_mode=WriteMode.WRITE if write else WriteMode.DRY_RUN,
        )
        self.store.save_run(run)
        self.store.add_event(
            run, "run", "started", "Ingestion run started"
        )
        try:
            inspection = inspect_input_file(InspectFileInput(file_path=file_path))
            run.source = inspection
            self.store.add_event(
                run,
                "inspection",
                "completed",
                f"Detected {inspection.modality.value} input",
                tool_name="inspect_input_file",
                tool_version="2.0.0",
                metrics={"size_bytes": inspection.size_bytes},
            )

            extraction = extract_supported_file(ExtractFileInput(
                file_path=file_path,
                force_ocr=force_ocr,
            ))
            self.store.save_artifact(run.run_id, "extraction.json", extraction)
            self.store.add_event(
                run,
                "extraction",
                "partial" if extraction.warnings else "completed",
                f"Extracted {len(extraction.records)} candidate record(s)",
                tool_name="extract_supported_file",
                tool_version="2.0.0",
                metrics=extraction.metrics.model_dump(mode="json"),
            )

            request = MappingRequest(
                run_id=run.run_id,
                inspection=inspection,
                extraction=extraction,
            )
            mapping_plan = plan or self.planner.propose(request)
            run.mapping_plan = mapping_plan
            run.target_collection = mapping_plan.target_collection
            mapping = apply_mapping_plan(request, mapping_plan)
            self.store.save_artifact(run.run_id, "mapping.json", mapping)
            self.store.add_event(
                run,
                "mapping_validation",
                "partial" if mapping.records_rejected else "completed",
                (
                    f"Validated {mapping.records_valid}/"
                    f"{mapping.records_attempted} mapped record(s)"
                ),
                tool_name="propose_and_apply_mapping",
                tool_version="2.0.0",
                metrics={
                    "records_attempted": mapping.records_attempted,
                    "records_valid": mapping.records_valid,
                    "records_rejected": mapping.records_rejected,
                    "required_field_coverage": mapping.required_field_coverage,
                    "validation_rate": mapping.validation_rate,
                },
            )

            persistence = persist_validated_records(
                PersistInput(
                    run_id=run.run_id,
                    write_mode=run.write_mode,
                    records=mapping.records,
                ),
                database=self.database,
            )
            self.store.save_artifact(run.run_id, "persistence.json", persistence)
            self.store.add_event(
                run,
                "persistence",
                "completed",
                (
                    "Dry-run validation completed without database writes"
                    if not write
                    else f"Persisted {persistence.inserted} new record(s)"
                ),
                tool_name="persist_validated_records",
                tool_version="2.0.0",
                metrics=persistence.model_dump(mode="json"),
            )

            valid = mapping.records_valid
            # MongoDB's modified count is a subset of matched count, not an
            # additional set of records.
            persisted = persistence.inserted + persistence.matched
            run.metrics = RunMetrics(
                source_units_attempted=extraction.metrics.source_units_attempted,
                source_units_extracted=extraction.metrics.source_units_extracted,
                candidate_records=mapping.records_attempted,
                valid_records=valid,
                rejected_records=mapping.records_rejected,
                inserted=persistence.inserted,
                matched=persistence.matched,
                modified=persistence.modified,
                extraction_coverage=extraction.metrics.extraction_coverage,
                required_field_coverage=mapping.required_field_coverage,
                validation_rate=mapping.validation_rate,
                persistence_rate=(
                    persisted / valid if write and valid else 0
                ),
            )
            run.warnings.extend(extraction.warnings)
            run.status = (
                RunStatus.PARTIAL
                if extraction.warnings or mapping.records_rejected
                else RunStatus.COMPLETED
            )
            run.completed_at = utc_now()
            self.store.add_event(
                run, "run", run.status.value, "Ingestion run finished"
            )
            return run
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.completed_at = utc_now()
            run.failures.append(f"{type(exc).__name__}: {exc}")
            self.store.add_event(
                run,
                "run",
                "failed",
                str(exc),
                error_type=type(exc).__name__,
            )
            raise
