"""Batch membership is enforced even when the model ignores its schema."""
import unittest
from ingestion_v2.models import SemanticFactBatchProposal
from ingestion_v2.semantic_facts import SemanticDocumentFactAgent
from tests.test_semantic_document_facts import candidate, fact_request, FakeStructuredModel


class RecordingModel(FakeStructuredModel):
    def __init__(self, proposals):
        super().__init__(proposals)
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return self


class BatchScopeTests(unittest.TestCase):
    def test_schema_ids_are_exact_noncontiguous_batch_ids(self):
        request = fact_request(contents=['one', 'two', 'three'])
        for record, index in zip(request.extraction.records, [2, 7, 19]):
            record.record_index = index
        model = RecordingModel([{'facts': []}, {'facts': []}])
        SemanticDocumentFactAgent(model).extract(request)
        enums = [s['$defs']['SemanticFactCandidate']['properties']['source_record_index']['enum']
                 for s in model.schemas]
        self.assertEqual(enums, [[2, 7], [19]])

    def test_foreign_batch_id_rejected_without_losing_valid_sibling(self):
        request = fact_request()
        content = request.extraction.records[0].data['content']
        request = fact_request(contents=[content, content])
        request.batch_size = 1
        model = RecordingModel([
            {'facts': [candidate(source_record_index=1).model_dump(),
                       candidate(source_record_index=0).model_dump()]},
            {'facts': []},
        ])
        output = SemanticDocumentFactAgent(model).extract(request)
        self.assertEqual(output.facts_proposed, 2)
        self.assertEqual(output.facts_valid, 1)
        self.assertEqual(output.facts_rejected, 1)
        self.assertEqual(output.duplicate_facts_removed, 0)
        self.assertIn('supplied batch', output.records[0].validation_errors[0])
        self.assertTrue(output.records[1].valid)

    def test_rejected_quote_cannot_suppress_grounded_later_batch(self):
        request = fact_request(contents=['unrelated text',
            'मखाना रिपोर्ट। भारत वैश्विक आपूर्ति में 90 प्रतिशत की हिस्सेदारी रखता है।'])
        request.batch_size = 1
        model = RecordingModel([
            SemanticFactBatchProposal(facts=[candidate(source_record_index=0)]),
            SemanticFactBatchProposal(facts=[candidate(source_record_index=1)]),
        ])
        output = SemanticDocumentFactAgent(model).extract(request)
        self.assertEqual((output.facts_valid, output.facts_rejected), (1, 1))
        self.assertEqual(output.duplicate_facts_removed, 0)

    def test_grounded_overlap_still_deduplicated_across_batches(self):
        content = fact_request().extraction.records[0].data['content']
        request = fact_request(contents=[content, content])
        request.batch_size = 1
        model = RecordingModel([
            {'facts': [candidate(source_record_index=0).model_dump()]},
            {'facts': [candidate(source_record_index=1).model_dump()]},
        ])
        output = SemanticDocumentFactAgent(model).extract(request)
        self.assertEqual((output.facts_valid, output.facts_rejected), (1, 0))
        self.assertEqual(output.duplicate_facts_removed, 1)

    def test_generation_enum_survives_langchain_tool_conversion(self):
        from langchain_core.utils.function_calling import convert_to_openai_tool
        request = fact_request()
        model = RecordingModel([{'facts': []}])
        SemanticDocumentFactAgent(model).extract(request)
        parameters = convert_to_openai_tool(model.schemas[0])['function']['parameters']
        self.assertEqual(parameters['$defs']['SemanticFactCandidate']['properties']
                         ['source_record_index']['enum'], [0])
