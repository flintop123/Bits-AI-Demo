"""Small, dependency-free client for the local Ollama chat API."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaUnavailableError(RuntimeError):
    """Raised when the configured local Ollama service cannot answer."""


class OllamaClient:
    def __init__(self, base_url=None, model=None, timeout=None):
        self.base_url = (
            base_url
            or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        ).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen3:4b")
        self.timeout = int(
            timeout
            if timeout is not None
            else os.getenv("OLLAMA_TIMEOUT_SECONDS", "600")
        )

    def _chat(self, messages, response_format=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "10m",
            "options": {
                "temperature": 0,
                "num_ctx": 4096,
                "num_predict": 512,
            },
        }
        if response_format is not None:
            payload["format"] = response_format
        request = Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OllamaUnavailableError(
                f"Ollama returned HTTP {exc.code}: {detail}"
            ) from exc
        except TimeoutError as exc:
            raise OllamaUnavailableError(
                f"Ollama did not respond within {self.timeout} seconds."
            ) from exc
        except (URLError, OSError) as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise OllamaUnavailableError(
                    f"Ollama did not respond within {self.timeout} seconds."
                ) from exc
            raise OllamaUnavailableError(
                "Ollama is unavailable. Start Ollama and verify the configured "
                f"model '{self.model}'."
            ) from exc
        except json.JSONDecodeError as exc:
            raise OllamaUnavailableError(
                "Ollama returned an invalid API response."
            ) from exc

        content = body.get("message", {}).get("content")
        if not content:
            raise OllamaUnavailableError(
                "Ollama returned an empty response."
            )
        return content.strip()

    def chat_text(self, messages):
        """Return a deterministic plain-text response from the local model."""
        return self._chat(messages)

    def chat_json(self, messages, schema):
        content = self._chat(messages, response_format=schema)
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaUnavailableError(
                "Ollama did not return the requested structured JSON."
            ) from exc
