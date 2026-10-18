"""Local multilingual embeddings through the Ollama HTTP API."""

import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaEmbeddingUnavailableError(RuntimeError):
    """Raised when the configured embedding model cannot answer."""


class OllamaEmbeddingClient:
    """Generate normalized embeddings without an additional Python SDK."""

    def __init__(self, base_url=None, model=None, timeout=300):
        self.base_url = (
            base_url
            or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        ).rstrip("/")
        self.model = model or os.getenv(
            "OLLAMA_EMBEDDING_MODEL", "bge-m3"
        )
        self.timeout = timeout

    def embed_query(self, text):
        return self.embed_texts([text])[0]

    def embed_texts(self, texts):
        values = [str(text or "").strip() for text in texts]
        if not values or any(not value for value in values):
            raise ValueError("embedding text must not be blank")

        try:
            embeddings = self._post_batch(values)
        except HTTPError as exc:
            if exc.code != 404:
                self._raise_http_error(exc)
            embeddings = [self._post_legacy(value) for value in values]
        except (URLError, TimeoutError, OSError) as exc:
            raise OllamaEmbeddingUnavailableError(
                "Ollama embeddings are unavailable. Start Ollama and verify "
                f"the model '{self.model}' with: ollama pull {self.model}"
            ) from exc

        if len(embeddings) != len(values):
            raise OllamaEmbeddingUnavailableError(
                "Ollama returned an unexpected number of embeddings."
            )
        return [self._normalize(vector) for vector in embeddings]

    def _post_batch(self, texts):
        payload = {
            "model": self.model,
            "input": texts,
            "truncate": True,
            "keep_alive": "30s",
        }
        body = self._request("/api/embed", payload)
        embeddings = body.get("embeddings")
        if not isinstance(embeddings, list):
            raise OllamaEmbeddingUnavailableError(
                "Ollama returned an invalid embedding response."
            )
        return embeddings

    def _post_legacy(self, text):
        body = self._request(
            "/api/embeddings",
            {"model": self.model, "prompt": text, "keep_alive": "30s"},
        )
        embedding = body.get("embedding")
        if not isinstance(embedding, list):
            raise OllamaEmbeddingUnavailableError(
                "Ollama returned an invalid legacy embedding response."
            )
        return embedding

    def _request(self, path, payload):
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError:
            raise
        except json.JSONDecodeError as exc:
            raise OllamaEmbeddingUnavailableError(
                "Ollama returned invalid JSON for an embedding request."
            ) from exc

    @staticmethod
    def _normalize(vector):
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise OllamaEmbeddingUnavailableError(
                "Ollama returned a non-numeric embedding."
            ) from exc
        magnitude = math.sqrt(sum(value * value for value in values))
        if not values or magnitude == 0:
            raise OllamaEmbeddingUnavailableError(
                "Ollama returned an empty or zero embedding."
            )
        return [value / magnitude for value in values]

    @staticmethod
    def _raise_http_error(exc):
        detail = exc.read().decode("utf-8", errors="replace")
        raise OllamaEmbeddingUnavailableError(
            f"Ollama embedding request returned HTTP {exc.code}: {detail}"
        ) from exc
