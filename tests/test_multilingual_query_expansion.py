import unittest

from services.multilingual_query_expansion import expand_document_query


class MultilingualQueryExpansionTests(unittest.TestCase):
    def test_hindi_organic_corridor_adds_english_source_vocabulary(self):
        expanded = expand_document_query(
            "गंगा नदी के किनारे जैविक कॉरिडोर कितने जिलों में है?"
        )

        self.assertIn("organic", expanded)
        self.assertIn("corridor", expanded)
        self.assertIn("Ganga", expanded)
        self.assertIn("district", expanded)

    def test_english_makhana_query_adds_hindi_source_vocabulary(self):
        expanded = expand_document_query("makhana processing handbook")

        self.assertIn("मखाना", expanded)
        self.assertIn("प्रसंस्करण", expanded)
        self.assertIn("पुस्तिका", expanded)

    def test_expansion_respects_length_limit(self):
        expanded = expand_document_query(
            "organic corridor Ganga district agriculture", max_length=50
        )

        self.assertLessEqual(len(expanded), 50)


if __name__ == "__main__":
    unittest.main()
