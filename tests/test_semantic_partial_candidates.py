"""Structural model errors are isolated to their own fact, not hidden."""
import unittest
from pydantic import ValidationError
from ingestion_v2.semantic_facts import SemanticDocumentFactAgent
from tests.test_semantic_document_facts import candidate, fact_request, FakeStructuredModel


class PartialCandidateTests(unittest.TestCase):
    def test_incomplete_seventh_fact_keeps_six_and_later_input_works(self):
        facts = []
        for i in range(6):
            fact = candidate().model_dump()
            fact['subject'] = 'Grounded proposal ' + str(i)
            facts.append(fact)
        facts.append({'source_record_index': 0, 'fact_type': 'scheme_metric',
                      'subject': 'UNSAFE_MODEL_TEXT'})
        model = FakeStructuredModel([{'facts': facts},
                                     {'facts': [candidate().model_dump()]}])
        agent = SemanticDocumentFactAgent(model)
        output = agent.extract(fact_request())
        self.assertEqual((output.facts_proposed, output.facts_valid,
                          output.facts_rejected, output.duplicate_facts_removed),
                         (7, 6, 1, 0))
        self.assertEqual([r.data['subject'] for r in output.records[:6]],
                         ['Grounded proposal ' + str(i) for i in range(6)])
        rejected = output.records[6]
        self.assertEqual(rejected.data, {})
        self.assertEqual(rejected.field_provenance, {})
        self.assertEqual(rejected.mapping_confidence, 0)
        self.assertIn('missing', rejected.validation_errors[0])
        self.assertNotIn('UNSAFE_MODEL_TEXT', rejected.model_dump_json())
        later = agent.extract(fact_request())
        self.assertEqual((later.facts_proposed, later.facts_valid, later.facts_rejected),
                         (1, 1, 0))

    def test_malformed_middle_entry_keeps_order_and_valid_siblings(self):
        first = candidate().model_dump()
        last = dict(first, subject='Second valid proposal')
        output = SemanticDocumentFactAgent(FakeStructuredModel([
            {'facts': [first, 'UNSAFE_MODEL_TEXT', last]}
        ])).extract(fact_request())
        self.assertEqual([r.valid for r in output.records], [True, False, True])
        self.assertEqual((output.facts_proposed, output.facts_rejected), (3, 1))
        self.assertNotIn('UNSAFE_MODEL_TEXT', output.model_dump_json())

    def test_invalid_envelope_fails_instead_of_empty_success(self):
        for envelope in [None, [], {}, {'facts': None}, {'facts': {}},
                         {'facts': '[]'}, {'facts': ()},
                         {'facts': [], 'unexpected': 'value'}]:
            with self.subTest(envelope=envelope), self.assertRaises(ValidationError):
                SemanticDocumentFactAgent(FakeStructuredModel([envelope])).extract(
                    fact_request())

    def test_all_malformed_facts_are_audited_rejections(self):
        output = SemanticDocumentFactAgent(FakeStructuredModel([
            {'facts': [None, {}, 3]}
        ])).extract(fact_request())
        self.assertEqual((output.facts_proposed, output.facts_valid,
                          output.facts_rejected), (3, 0, 3))

    def test_valid_empty_envelope_is_allowed(self):
        output = SemanticDocumentFactAgent(FakeStructuredModel([
            {'facts': []}
        ])).extract(fact_request())
        self.assertEqual(output.facts_proposed, 0)
        self.assertEqual(output.records, [])
