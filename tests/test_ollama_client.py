import json
import unittest
from unittest.mock import patch

from services.ollama_client import OllamaClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class OllamaClientTests(unittest.TestCase):
    @patch("services.ollama_client.urlopen")
    def test_plain_text_chat_does_not_request_json_format(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeResponse({
            "message": {"content": "  हिंदी उत्तर।  "}
        })
        client = OllamaClient(model="qwen3:4b")

        result = client.chat_text([{"role": "user", "content": "प्रश्न"}])

        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result, "हिंदी उत्तर।")
        self.assertNotIn("format", payload)
        self.assertFalse(payload["think"])
        self.assertEqual(payload["keep_alive"], "10m")
        self.assertEqual(payload["options"]["num_ctx"], 4096)
        self.assertEqual(payload["options"]["num_predict"], 512)

    def test_default_timeout_allows_slow_local_cpu_generation(self):
        client = OllamaClient()

        self.assertEqual(client.timeout, 600)


if __name__ == "__main__":
    unittest.main()
