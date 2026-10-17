"""Small, dependency-free client for the local Ollama chat API."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaUnavailableError(RuntimeError):
    """Raised when the configured local Ollama service cannot answer."""


class OllamaClient:
    def __init__(self, base_url=None, model=None, timeout=180):
        self.base_url = (
            base_url
            or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        ).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen3:4b")
        self.timeout = timeout

    def chat_json(self, messages, schema):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "30s",
            "format": schema,
            "options": {"temperature": 0},
        }
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
        except (URLError, TimeoutError, OSError) as exc:
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
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaUnavailableError(
                "Ollama did not return the requested structured JSON."
            ) from exc
