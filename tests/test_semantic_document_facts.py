import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ingestion_v2.models import (
    ExtractFileOutput,
    ExtractedRecord,
    ExtractionMetrics,
    ExtractSemanticFactsInput,
    FieldMapping,
    InspectFileOutput,
    MappingPlan,
    PersistInput,
    SemanticFactBatchProposal,
    SemanticFactCandidate,
    SourceLocator,
    SourceModality,
    TargetCollection,
    WriteMode,
)
from ingestion_v2.persistence import persist_validated_records
from ingestion_v2.pipeline import AgenticIngestionPipeline
from ingestion_v2.run_store import LocalIngestionRunStore
from ingestion_v2.semantic_facts import SemanticDocumentFactAgent
from run_ingestion_v2 import parse_args


def candidate(
    *,
    source_record_index=0,
    evidence_quote=(
        "भारत वैश्विक आपूर्ति में 90 प्रतिशत की हिस्सेदारी रखता है।"
    ),
    value_as_reported="90 प्रतिशत",
    confidence=0.96,
    normalized_value=90,
    normalized_unit="percent",
    unit_as_reported="प्रतिशत",
    geography="भारत",
    crop="मखाना",
):
    return SemanticFactCandidate(
        source_record_index=source_record_index,
        fact_type="market_metric",
        subject="India makhana supply share",
        metric="global_supply_share",
        value_as_reported=value_as_reported,
        normalized_value=normalized_value,
        unit_as_reported=unit_as_reported,
        normalized_unit=normalized_unit,
        period=None,
        geography=geography,
        crop=crop,
        scheme_name=None,
        evidence_quote=evidence_quote,
        confidence=confidence,
    )


def fact_request(*, contents=None, minimum_confidence=0.85):
    contents = contents or [
        "मखाना रिपोर्ट। भारत वैश्विक आपूर्ति में 90 प्रतिशत की हिस्सेदारी रखता है।"
    ]
    records = []
    for index, content in enumerate(contents):
        locator = SourceLocator(
            source_file="makhana.pdf",
            source_url="file:///inputs/makhana.pdf",
            modality=SourceModality.PDF,
            page_number=index + 1,
            chunk_index=0,
        )
        data = {
            "document_title": "Makhana report",
            "page_number": index + 1,
            "chunk_index": 0,
            "content": content,
            "language": "hi",
            "extraction_method": "tesseract_ocr",
            "source_type": "pdf",
            "source_url": "file:///inputs/makhana.pdf",
            "source_file": "makhana.pdf",
            "content_hash": str(index) * 64,
        }
        records.append(ExtractedRecord(
            record_index=index,
            data=data,
            field_locators={key: locator for key in data},
            record_locator=locator,
        ))
    inspection = InspectFileOutput(
        file_path="C:/inputs/makhana.pdf",
        source_file="makhana.pdf",
        source_hash="a" * 64,
        size_bytes=1000,
        modality=SourceModality.PDF,
        mime_type="application/pdf",
        supported=True,
    )
    extraction = ExtractFileOutput(
        modality=SourceModality.PDF,
        extraction_method="pypdf_tesseract_extractor",
        records=records,
        metrics=ExtractionMetrics(
            source_units_attempted=len(records),
            source_units_extracted=len(records),
            records_extracted=len(records),
            units_skipped=0,
            extraction_coverage=1,
        ),
    )
    return ExtractSemanticFactsInput(
        run_id="semantic-run",
        inspection=inspection,
        extraction=extraction,
        max_chunks=40,
        batch_size=2,
        minimum_confidence=minimum_confidence,
    )


class FakeStructuredModel:
    def __init__(self, proposals):
        self.proposals = list(proposals)
        self.prompts = []

    def with_structured_output(self, _schema):
        return self

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.proposals.pop(0)


class FakeDatabase:
    def __init__(self):
        self.records = []

    def upsert_records(self, records):
        self.records.extend(records)
        return {"inserted": len(records), "matched": 0, "modified": 0}


class SemanticDocumentFactTests(unittest.TestCase):
    def test_cli_exposes_bounded_semantic_fact_options(self):
        args = parse_args([
            "--input", "report.pdf", "--semantic-facts",
            "--max-fact-chunks", "12", "--fact-batch-size", "3",
        ])
        self.assertTrue(args.semantic_facts)
        self.assertEqual(args.max_fact_chunks, 12)
        self.assertEqual(args.fact_batch_size, 3)

    def test_cli_rejects_unbounded_fact_chunk_count(self):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                parse_args([
                    "--input", "report.pdf", "--semantic-facts",
                    "--max-fact-chunks", "1000",
                ])

    def test_quote_anchored_fact_retains_page_chunk_and_character_offsets(self):
        proposal = SemanticFactBatchProposal(facts=[candidate()])
        output = SemanticDocumentFactAgent(
            FakeStructuredModel([proposal])
        ).extract(fact_request())

        self.assertEqual(output.target_collection, TargetCollection.AGRICULTURE_FACTS)
        self.assertEqual(output.facts_valid, 1)
        record = output.records[0]
        database = FakeDatabase()
        persisted = persist_validated_records(
            PersistInput(
                run_id="semantic-run",
                write_mode=WriteMode.WRITE,
                records=output.records,
            ),
            database=database,
        )
        self.assertTrue(record.valid)
        self.assertEqual(record.data["value_as_reported"], "90 प्रतिशत")
        self.assertEqual(record.data["page_number"], 1)
        self.assertEqual(record.data["chunk_index"], 0)
        self.assertEqual(record.data["evidence_validation"], "exact_quote")
        locator = record.field_provenance["value_as_reported"].locator
        self.assertIsNotNone(locator.text_start)
        self.assertGreater(locator.text_end, locator.text_start)
        self.assertEqual(len(record.data["fact_id"]), 64)

    def test_hallucinated_quote_is_rejected_and_never_persisted(self):
        proposal = SemanticFactBatchProposal(facts=[candidate(
            evidence_quote="बिहार का योगदान 100 प्रतिशत है।",
            value_as_reported="100 प्रतिशत",
        )])
        output = SemanticDocumentFactAgent(
            FakeStructuredModel([proposal])
        ).extract(fact_request())
        database = FakeDatabase()
        persisted = persist_validated_records(
            PersistInput(
                run_id="semantic-run",
                write_mode=WriteMode.WRITE,
                records=output.records,
            ),
            database=database,
        )

        self.assertEqual(output.facts_rejected, 1)
        self.assertIn("evidence_quote", output.records[0].validation_errors[0])
        self.assertEqual(persisted.rejected, 1)
        self.assertEqual(database.records, [])

    def test_verified_high_confidence_fact_is_write_eligible(self):
        output = SemanticDocumentFactAgent(
            FakeStructuredModel([
                SemanticFactBatchProposal(facts=[candidate()])
            ])
        ).extract(fact_request())
        database = FakeDatabase()
        persisted = persist_validated_records(
            PersistInput(
                run_id="semantic-run",
                write_mode=WriteMode.WRITE,
                records=output.records,
            ),
            database=database,
        )

        self.assertEqual(persisted.inserted, 1)
        self.assertEqual(persisted.quarantined, 0)
        self.assertEqual(len(database.records), 1)
        self.assertEqual(
            database.records[0]["review_status"], "approved_for_write"
        )

    def test_value_must_be_present_inside_the_evidence_quote(self):
        proposal = SemanticFactBatchProposal(facts=[candidate(
            value_as_reported="85 प्रतिशत",
        )])
        output = SemanticDocumentFactAgent(
            FakeStructuredModel([proposal])
        ).extract(fact_request())

        self.assertEqual(output.facts_valid, 0)
        self.assertTrue(any(
            "value_as_reported" in error
            for error in output.records[0].validation_errors
        ))

    def test_low_confidence_fact_requires_review_and_is_quarantined(self):
        proposal = SemanticFactBatchProposal(facts=[candidate(confidence=0.60)])
        output = SemanticDocumentFactAgent(
            FakeStructuredModel([proposal])
        ).extract(fact_request())
        database = FakeDatabase()
        persisted = persist_validated_records(
            PersistInput(
                run_id="semantic-run",
                write_mode=WriteMode.WRITE,
                records=output.records,
            ),
            database=database,
        )

        self.assertEqual(output.facts_review_required, 1)
        self.assertEqual(
            output.records[0].data["review_status"], "human_review_required"
        )
        self.assertEqual(persisted.quarantined, 1)
        self.assertEqual(database.records, [])

    def test_unverified_model_unit_scaling_requires_review(self):
        quote = "पोर्टल पर 1.84 करोड़ किसान पंजीकृत हैं।"
        proposal = SemanticFactBatchProposal(facts=[candidate(
            evidence_quote=quote,
            value_as_reported="1.84 करोड़",
            normalized_value=18400000,
            normalized_unit="count",
            unit_as_reported="करोड़",
            geography=None,
            crop=None,
        )])
        output = SemanticDocumentFactAgent(
            FakeStructuredModel([proposal])
        ).extract(fact_request(contents=[quote]))

        record = output.records[0]
        database = FakeDatabase()
        persisted = persist_validated_records(
            PersistInput(
                run_id="semantic-run",
                write_mode=WriteMode.WRITE,
                records=output.records,
            ),
            database=database,
        )
        self.assertTrue(record.valid)
        self.assertEqual(
            record.data["normalization_status"],
            "model_proposed_requires_review",
        )
        self.assertEqual(record.data["review_status"], "human_review_required")
        self.assertEqual(persisted.quarantined, 1)
        self.assertEqual(database.records, [])

    def test_overlapping_chunk_fact_is_deduplicated(self):
        quote = "भारत वैश्विक आपूर्ति में 90 प्रतिशत की हिस्सेदारी रखता है।"
        proposal = SemanticFactBatchProposal(facts=[
            candidate(source_record_index=0),
            candidate(source_record_index=1),
        ])
        output = SemanticDocumentFactAgent(
            FakeStructuredModel([proposal])
        ).extract(fact_request(contents=[quote, quote]))

        self.assertEqual(output.facts_proposed, 2)
        self.assertEqual(output.duplicate_facts_removed, 1)
        self.assertEqual(len(output.records), 1)

    def test_non_pdf_input_is_rejected(self):
        request = fact_request()
        request.inspection.modality = SourceModality.JSON
        with self.assertRaisesRegex(ValueError, "requires PDF"):
            SemanticDocumentFactAgent(
                FakeStructuredModel([])
            ).extract(request)

    def test_pipeline_records_semantic_fact_artifacts_and_metrics(self):
        request = fact_request()
        proposal = SemanticFactBatchProposal(facts=[candidate()])
        fact_agent = SemanticDocumentFactAgent(FakeStructuredModel([proposal]))
        document_fields = (
            "document_title", "page_number", "chunk_index", "content",
            "language", "extraction_method", "source_type", "source_url",
            "source_file", "content_hash",
        )
        plan = MappingPlan(
            target_collection=TargetCollection.AGRICULTURE_DOCUMENTS,
            field_mappings=[
                FieldMapping(
                    source_field=field,
                    target_field=field,
                    transformation=(
                        "integer"
                        if field in {"page_number", "chunk_index"}
                        else "identity"
                    ),
                )
                for field in document_fields
            ],
            identity_fields=[
                "source_url", "page_number", "chunk_index", "content_hash"
            ],
            confidence=0.99,
            explanation="Canonical page-aware PDF chunks",
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pipeline = AgenticIngestionPipeline(
                store=LocalIngestionRunStore(root / "artifacts"),
                fact_agent=fact_agent,
            )
            with patch(
                "ingestion_v2.pipeline.inspect_input_file",
                return_value=request.inspection,
            ), patch(
                "ingestion_v2.pipeline.extract_supported_file",
                return_value=request.extraction,
            ):
                run = pipeline.run(
                    "C:/inputs/makhana.pdf",
                    plan=plan,
                    semantic_facts=True,
                )
            files = {
                path.name
                for path in (root / "artifacts" / run.run_id).iterdir()
            }

        self.assertEqual(run.status.value, "completed")
        self.assertEqual(run.metrics.semantic_chunks_examined, 1)
        self.assertEqual(run.metrics.semantic_facts_valid, 1)
        self.assertEqual(run.metrics.semantic_facts_rejected, 0)
        self.assertTrue({
            "semantic_facts.json", "semantic_fact_persistence.json"
        } <= files)


if __name__ == "__main__":
    unittest.main()
