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
from ingestion_v2.mapping import SchemaMappingAgent, apply_mapping_plan
from ingestion_v2.models import (
    ExtractFileInput,
    ExtractFileOutput,
    ExtractedRecord,
    ExtractionMetrics,
    FieldMapping,
    InspectFileInput,
    InspectFileOutput,
    MappingPlan,
    MappingRequest,
    PersistInput,
    SeriesColumn,
    SeriesMapping,
    SourceModality,
    SourceLocator,
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
    def test_pdf_extractor_contract_rejects_incompatible_model_target(self):
        locator = SourceLocator(
            source_file="makhana.pdf",
            source_url="file:///makhana.pdf",
            modality=SourceModality.PDF,
            page_number=1,
            chunk_index=0,
        )
        data = {
            "document_title": "Makhana report",
            "page_number": 1,
            "chunk_index": 0,
            "content": "मखाना उत्पादन और प्रसंस्करण की जानकारी।",
            "language": "hi",
            "extraction_method": "tesseract_ocr",
            "source_type": "pdf",
            "source_url": "file:///makhana.pdf",
            "source_file": "makhana.pdf",
            "content_hash": "a" * 64,
        }
        inspection = InspectFileOutput(
            file_path="/tmp/makhana.pdf",
            source_file="makhana.pdf",
            source_hash="b" * 64,
            size_bytes=100,
            modality=SourceModality.PDF,
            mime_type="application/pdf",
            supported=True,
        )
        extraction = ExtractFileOutput(
            modality=SourceModality.PDF,
            extraction_method="pypdf_tesseract_extractor",
            records=[ExtractedRecord(
                record_index=0,
                data=data,
                field_locators={key: locator for key in data},
                record_locator=locator,
            )],
            metrics=ExtractionMetrics(
                source_units_attempted=1,
                source_units_extracted=1,
                records_extracted=1,
                units_skipped=0,
                extraction_coverage=1,
            ),
        )
        request = MappingRequest(
            run_id="run-pdf-contract",
            inspection=inspection,
            extraction=extraction,
        )
        incompatible = MappingPlan(
            target_collection=TargetCollection.MANDI_LOCATIONS,
            field_mappings=[],
            identity_fields=["market_code", "market_name"],
            confidence=0.91,
            explanation="Incorrectly interpreted narrative locations",
        )

        class FakeStructuredModel:
            def with_structured_output(self, _schema):
                return self

            def invoke(self, _prompt):
                return incompatible

        plan = SchemaMappingAgent(FakeStructuredModel()).propose(request)
        output = apply_mapping_plan(request, plan)

        self.assertEqual(
            plan.target_collection, TargetCollection.AGRICULTURE_DOCUMENTS
        )
        self.assertIn("incompatible target mandi_locations", plan.explanation)
        self.assertEqual(output.records_valid, 1)
        self.assertEqual(output.records[0].data["language"], "hi")

    def test_agent_repairs_wide_excel_plan_from_explicit_header(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "wide-statistics.xlsx"
            pd.DataFrame([
                ["Bihar crop statistics", None, None, None, None, None, None, None],
                ["Place: Bihar", None, None, None, None, None, None, None],
                ["Reporting periods", None, None, None, None, None, None, None],
                ["Source note", None, None, None, None, None, None, None],
                [None, None, None, None, None, None, None, None],
                [
                    "Crop", "Season", "Area (ha) 2023-24", "Area (ha) 2024-25",
                    "Production (tonnes) 2023-24", "Production (tonnes) 2024-25",
                    "Yield (kg/ha) 2023-24", "Yield (kg/ha) 2024-25",
                ],
                ["Wheat", "Total", 2275578, 2250610, 7168070.7, 7119804.74, 3150, 3164],
            ]).to_excel(path, sheet_name="Bihar crops", header=False, index=False)
            inspection = inspect_input_file(InspectFileInput(file_path=str(path)))
            extraction = extract_supported_file(ExtractFileInput(file_path=str(path)))
            request = MappingRequest(
                run_id="run-wide-repair", inspection=inspection,
                extraction=extraction,
            )
            incomplete = MappingPlan(
                target_collection=TargetCollection.CROP_STATISTICS,
                field_mappings=[
                    FieldMapping(source_field="A", target_field="crop"),
                    FieldMapping(source_field="B", target_field="season"),
                ],
                identity_fields=["crop", "season", "year"],
                confidence=0.85,
                explanation="The workbook contains wide period columns",
            )

            class FakeStructuredModel:
                def with_structured_output(self, _schema):
                    return self

                def invoke(self, _prompt):
                    return incomplete

            plan = SchemaMappingAgent(FakeStructuredModel()).propose(request)
            output = apply_mapping_plan(request, plan)

        self.assertEqual(plan.source_scope, "Bihar crops")
        self.assertEqual(plan.data_start_row, 7)
        self.assertEqual(len(plan.series_mappings), 3)
        self.assertEqual(
            sum(len(item.columns) for item in plan.series_mappings), 6
        )
        self.assertEqual(output.records_attempted, 2)
        self.assertEqual(output.records_valid, 2)
        self.assertEqual(
            output.records[0].field_provenance["year"].mapping_method,
            "wide_header_schema_safeguard",
        )

    def test_agent_restores_exact_required_field_omitted_by_model(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps([{
                "district": "Arwal",
                "market": "Arwal",
                "date": "2026-10-17",
                "crop": "Potato",
                "variety": "Local",
                "price": 1200,
                "unit": "quintal",
            }]), encoding="utf-8")
            inspection = inspect_input_file(InspectFileInput(file_path=str(path)))
            extraction = extract_supported_file(ExtractFileInput(file_path=str(path)))
            request = MappingRequest(
                run_id="run-repair", inspection=inspection, extraction=extraction
            )

            omitted_date_plan = mandi_plan().model_copy(update={
                "field_mappings": [
                    item for item in mandi_plan().field_mappings
                    if item.target_field != "date"
                ]
            })

            class FakeStructuredModel:
                def with_structured_output(self, _schema):
                    return self

                def invoke(self, _prompt):
                    return omitted_date_plan

            plan = SchemaMappingAgent(FakeStructuredModel()).propose(request)
            output = apply_mapping_plan(request, plan)

        date_mapping = next(
            item for item in plan.field_mappings if item.target_field == "date"
        )
        self.assertEqual(date_mapping.source_field, "date")
        self.assertEqual(date_mapping.transformation, "date")
        self.assertEqual(
            date_mapping.mapping_method, "exact_name_schema_safeguard"
        )
        self.assertEqual(output.records_valid, 1)
        self.assertEqual(
            output.records[0].field_provenance["date"].mapping_method,
            "exact_name_schema_safeguard",
        )

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
