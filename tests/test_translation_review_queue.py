import unittest

from scripts.export_translation_review_queue import build_review_queue


class TranslationReviewQueueTests(unittest.TestCase):
    def test_rejected_qwen_proposal_is_exported_for_review(self):
        documents = [{
            "entity_type": "crop",
            "official_value": "हल्दी",
            "official_language": "hi",
            "translation_evidence": {
                "en": {
                    "validation_status": "rejected_round_trip_mismatch",
                    "agentic_fallback": {
                        "model_name": "qwen3:4b",
                        "validation_status": (
                            "rejected_independent_round_trip_mismatch"
                        ),
                        "proposed_label": "turmeric",
                        "round_trip_candidate": "गोथिक",
                    },
                }
            },
        }]

        queue = build_review_queue(documents)

        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["official_value"], "हल्दी")
        self.assertEqual(queue[0]["proposed_label"], "turmeric")
        self.assertEqual(queue[0]["review_status"], "pending")

    def test_accepted_or_non_model_labels_are_not_exported(self):
        documents = [{
            "entity_type": "crop",
            "official_value": "आलू",
            "translation_evidence": {
                "en": {"validation_status": "accepted_reviewed_alias"}
            },
        }]

        self.assertEqual(build_review_queue(documents), [])


if __name__ == "__main__":
    unittest.main()
