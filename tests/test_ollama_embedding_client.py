import json
import unittest
from unittest.mock import patch

from services.ollama_embedding_client import OllamaEmbeddingClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class OllamaEmbeddingClientTests(unittest.TestCase):
    @patch("services.ollama_embedding_client.urlopen")
    def test_batch_embeddings_are_normalized(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeResponse({
            "embeddings": [[3.0, 4.0], [0.0, 2.0]],
        })
        client = OllamaEmbeddingClient(model="test-model")

        vectors = client.embed_texts(["first", "second"])

        self.assertAlmostEqual(vectors[0][0], 0.6)
        self.assertAlmostEqual(vectors[0][1], 0.8)
        self.assertEqual(vectors[1], [0.0, 1.0])

    def test_blank_embedding_input_is_rejected(self):
        client = OllamaEmbeddingClient(model="test-model")
        with self.assertRaisesRegex(ValueError, "must not be blank"):
            client.embed_query("  ")


if __name__ == "__main__":
    unittest.main()
