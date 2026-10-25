import json
import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from pydantic import ValidationError

from ingestion_v2.extraction import (
    extract_supported_file,
    inspect_input_file,
)
from ingestion_v2.mapping import apply_mapping_plan
from ingestion_v2.models import (
    ExtractFileInput,
    FieldMapping,
    InspectFileInput,
    MappingPlan,
    MappingRequest,
    PersistInput,
    SeriesColumn,
    SeriesMapping,
    SourceModality,
    TargetCollection,
    WriteMode,
)
from ingestion_v2.persistence import persist_validated_records
from ingestion_v2.pipeline import AgenticIngestionPipeline
from ingestion_v2.run_store import LocalIngestionRunStore
from ingestion_v2.tool_registry import TOOL_CONTRACTS


def mandi_plan():
    return MappingPlan(
        target_collection=TargetCollection.MANDI_PRICES,
        field_mappings=[
            FieldMapping(source_field=name, target_field=name, transformation=(
                "number" if "price" in name else
                "date" if name == "date" else "text"
            ))
            for name in (
                "district", "market", "date", "crop", "variety",
                "price", "minimum_price", "maximum_price", "unit",
            )
        ],
        identity_fields=[
            "district", "market", "date", "crop", "variety", "source_url"
        ],
        confidence=0.98,
        explanation="Flat normalized mandi records with explicit semantic keys",
    )


class InspectionAndExtractionTests(unittest.TestCase):
    def test_inspection_hashes_and_classifies_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_text("[]", encoding="utf-8")
            result = inspect_input_file(InspectFileInput(file_path=str(path)))
        self.assertEqual(result.modality, SourceModality.JSON)
        self.assertEqual(len(result.source_hash), 64)
        self.assertTrue(result.supported)

    def test_inspection_rejects_unsupported_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.docx"
            path.write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "Unsupported input type"):
                inspect_input_file(InspectFileInput(file_path=str(path)))

    def test_json_extraction_retains_jsonpath_per_field(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(
                json.dumps([{"district": "Patna", "price": 1200}]),
                encoding="utf-8",
            )
            result = extract_supported_file(ExtractFileInput(file_path=str(path)))
        self.assertEqual(result.records[0].field_locators["price"].json_path, "$[0].price")
        self.assertEqual(result.metrics.extraction_coverage, 1)

    def test_excel_extraction_retains_sheet_row_and_cell(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "statistics.xlsx"
            pd.DataFrame([["Crop", "Value"], ["Wheat", 12]]).to_excel(
                path, sheet_name="Data", header=False, index=False
            )
            result = extract_supported_file(ExtractFileInput(file_path=str(path)))
        self.assertEqual(result.records[1].record_locator.sheet_name, "Data")
        self.assertEqual(result.records[1].record_locator.row_number, 2)
        self.assertEqual(result.records[1].field_locators["B"].cell_reference, "B2")


class ToolContractTests(unittest.TestCase):
    def test_every_tool_has_input_and_output_json_schema(self):
        self.assertEqual(
            set(TOOL_CONTRACTS),
            {
                "inspect_input_file",
                "extract_supported_file",
                "propose_and_apply_mapping",
                "persist_validated_records",
            },
        )
        for contract in TOOL_CONTRACTS.values():
            self.assertEqual(contract.version, "2.0.0")
            self.assertIn("properties", contract.input_schema)
            self.assertIn("properties", contract.output_schema)

    def test_tool_input_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError):
            InspectFileInput(file_path="a.json", unknown=True)

    @unittest.skipUnless(
        importlib.util.find_spec("langchain_core"),
        "langchain-core is optional in the lightweight test environment",
    )
    def test_langchain_adapters_expose_structured_argument_schemas(self):
        from ingestion_v2.langchain_tools import default_ingestion_tools

        tools = default_ingestion_tools()
        self.assertEqual(len(tools), 4)
        for structured_tool in tools:
            self.assertIsNotNone(structured_tool.args_schema)
            self.assertTrue(structured_tool.args_schema.model_json_schema()["properties"])


class MappingTests(unittest.TestCase):
    def test_normalized_mandi_json_maps_and_validates(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps([{
                "district": "अरवल",
                "market": "अरवल",
                "date": "2026-10-17",
                "crop": "आलू",
                "variety": "Local",
                "price": 1200,
                "minimum_price": 1100,
                "maximum_price": 1250,
                "unit": "quintal",
            }], ensure_ascii=False), encoding="utf-8")
            inspection = inspect_input_file(InspectFileInput(file_path=str(path)))
            extraction = extract_supported_file(ExtractFileInput(file_path=str(path)))
            output = apply_mapping_plan(
                MappingRequest(
                    run_id="run-test", inspection=inspection, extraction=extraction
                ),
                mandi_plan(),
            )
        self.assertEqual(output.records_valid, 1)
        record = output.records[0]
        self.assertEqual(record.data["price"], 1200)
        self.assertEqual(
            record.field_provenance["price"].locator.json_path, "$[0].price"
        )
        self.assertEqual(record.data["extraction_run_id"], "run-test")
        self.assertTrue(record.data["source_record_id"])

    def test_wide_excel_series_is_unpivoted_to_period_records(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "statistics.xlsx"
            pd.DataFrame([
                ["Bihar crop statistics", None, None, None, None],
                ["Crop", "Season", "Area 2024-25", "Production 2024-25", "Yield 2024-25"],
                ["Wheat", "Total", 2250610, 7119804.74, 3164],
            ]).to_excel(path, sheet_name="Bihar crops", header=False, index=False)
            inspection = inspect_input_file(InspectFileInput(file_path=str(path)))
            extraction = extract_supported_file(ExtractFileInput(file_path=str(path)))
            plan = MappingPlan(
                target_collection=TargetCollection.CROP_STATISTICS,
                source_scope="Bihar crops",
                data_start_row=3,
                field_mappings=[
                    FieldMapping(source_field="A", target_field="crop", transformation="text"),
                    FieldMapping(source_field="B", target_field="season", transformation="text"),
                ],
                series_mappings=[
                    SeriesMapping(
                        target_field="area_hectares",
                        columns=[SeriesColumn(period="2024-25", source_field="C")],
                    ),
                    SeriesMapping(
                        target_field="production",
                        columns=[SeriesColumn(period="2024-25", source_field="D")],
                    ),
                    SeriesMapping(
                        target_field="yield_kg_per_hectare",
                        columns=[SeriesColumn(period="2024-25", source_field="E")],
                    ),
                ],
                static_values={
                    "area_unit": "hectare",
                    "production_unit": "tonne",
                    "yield_unit": "kg_per_hectare",
                },
                identity_fields=["crop", "season", "year"],
                confidence=0.99,
                explanation="Wide period columns unpivot into canonical records",
            )
            output = apply_mapping_plan(
                MappingRequest(
                    run_id="run-excel", inspection=inspection, extraction=extraction
                ),
                plan,
            )
        self.assertEqual(output.records_valid, 1)
        record = output.records[0]
        self.assertEqual(record.data["year"], "2024-25")
        self.assertEqual(record.data["production"], 7119804.74)
        self.assertEqual(
            record.field_provenance["production"].locator.cell_reference, "D3"
        )

    def test_missing_required_fields_are_rejected_not_silently_inserted(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps([{"district": "Patna"}]), encoding="utf-8")
            inspection = inspect_input_file(InspectFileInput(file_path=str(path)))
            extraction = extract_supported_file(ExtractFileInput(file_path=str(path)))
            output = apply_mapping_plan(
                MappingRequest(
                    run_id="run-invalid", inspection=inspection, extraction=extraction
                ),
                mandi_plan(),
            )
        self.assertEqual(output.records_valid, 0)
        self.assertEqual(output.records_rejected, 1)
        self.assertTrue(output.records[0].validation_errors)


class FakeDatabase:
    def __init__(self):
        self.records = []

    def upsert_records(self, records):
        self.records.extend(records)
        return {"inserted": len(records), "matched": 0, "modified": 0}


class PersistenceAndPipelineTests(unittest.TestCase):
    def _mapped_records(self, path):
        inspection = inspect_input_file(InspectFileInput(file_path=str(path)))
        extraction = extract_supported_file(ExtractFileInput(file_path=str(path)))
        return apply_mapping_plan(
            MappingRequest(
                run_id="run-persist", inspection=inspection, extraction=extraction
            ),
            mandi_plan(),
        ).records

    def test_dry_run_never_calls_database(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps([{
                "district": "Patna", "market": "Patna", "date": "2026-10-17",
                "crop": "Potato", "variety": "Local", "price": 1200,
                "minimum_price": 1100, "maximum_price": 1250, "unit": "quintal",
            }]), encoding="utf-8")
            records = self._mapped_records(path)
            database = FakeDatabase()
            result = persist_validated_records(
                PersistInput(
                    run_id="run-persist", write_mode=WriteMode.DRY_RUN,
                    records=records,
                ),
                database=database,
            )
        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.eligible, 1)
        self.assertEqual(database.records, [])

    def test_explicit_write_uses_allowlisted_connector(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps([{
                "district": "Patna", "market": "Patna", "date": "2026-10-17",
                "crop": "Potato", "variety": "Local", "price": 1200,
                "minimum_price": 1100, "maximum_price": 1250, "unit": "quintal",
            }]), encoding="utf-8")
            records = self._mapped_records(path)
            database = FakeDatabase()
            result = persist_validated_records(
                PersistInput(
                    run_id="run-persist", write_mode=WriteMode.WRITE,
                    records=records,
                ),
                database=database,
            )
        self.assertEqual(result.inserted, 1)
        self.assertEqual(len(database.records), 1)

    def test_low_confidence_record_is_quarantined_from_write(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps([{
                "district": "Patna", "market": "Patna", "date": "2026-10-17",
                "crop": "Potato", "variety": "Local", "price": 1200,
                "minimum_price": 1100, "maximum_price": 1250, "unit": "quintal",
            }]), encoding="utf-8")
            records = self._mapped_records(path)
            records[0].mapping_confidence = 0.50
            database = FakeDatabase()
            result = persist_validated_records(
                PersistInput(
                    run_id="run-low-confidence", write_mode=WriteMode.WRITE,
                    records=records,
                ),
                database=database,
            )
        self.assertEqual(result.quarantined, 1)
        self.assertEqual(result.eligible, 0)
        self.assertEqual(database.records, [])

    def test_pipeline_writes_stage_artifacts_without_touching_react(self):
        class Planner:
            def propose(self, _request):
                return mandi_plan()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "prices.json"
            path.write_text(json.dumps([{
                "district": "Patna", "market": "Patna", "date": "2026-10-17",
                "crop": "Potato", "variety": "Local", "price": 1200,
                "minimum_price": 1100, "maximum_price": 1250, "unit": "quintal",
            }]), encoding="utf-8")
            pipeline = AgenticIngestionPipeline(
                planner=Planner(),
                store=LocalIngestionRunStore(root / "artifacts"),
            )
            run = pipeline.run(str(path))
            run_dir = root / "artifacts" / run.run_id
            files = {item.name for item in run_dir.iterdir()}
        self.assertEqual(run.status.value, "completed")
        self.assertEqual(run.metrics.valid_records, 1)
        self.assertTrue(
            {"run.json", "events.jsonl", "extraction.json", "mapping.json", "persistence.json"}
            <= files
        )


if __name__ == "__main__":
    unittest.main()
