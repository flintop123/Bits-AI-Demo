"""An opt-in Milvus demo restricted to one reviewed public report.

Uses the existing retrieval/final-answer nodes with an injected connector.
Nothing here reads MongoDB, the team's config file, or a stored token.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
from urllib.parse import urlsplit

from services.ollama_embedding_client import OllamaEmbeddingClient


REPORT = "bihar_annual_scheme_2022_23.pdf"
TITLE = "Bihar Annual Scheme 2022-23 - Agriculture and Allied Sector"
SOURCE = (
    "https://betastate.bihar.gov.in/file_2/FileUpload/2024/Apr/18-Apr-2024/16/DyPage/"
    "f8cbff28-9f30-4b42-8557-75d10965d4b5.pdf"
)
QUESTION = "What does the report say about the organic farming corridor?"
REVIEWED_SHA256 = "25b5979a590e533c25f9bd1f024867c3c0a00cc0b0afb83608ecc96250a18e98"
DUMP = Path(__file__).resolve().parents[1] / "db" / "dump" / "agriculture_documents.jsonl"
DEMO_COLLECTION = re.compile(r"agriagent_demo_[a-f0-9]{12}\Z")
NAMED_COLLECTION = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}\Z")
_DIMENSION = 1024
_OLLAMA = "http://127.0.0.1:11434"


class DemoError(RuntimeError):
    """A safe message, never raw provider exception details."""


def public_passages():
    rows = {}
    for line in DUMP.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("source_file") != REPORT:
            continue
        page, chunk, text = row.get("page_number"), row.get("chunk_index"), row.get("content")
        if (row.get("source_url") != SOURCE or row.get("document_title") != TITLE
                or type(page) is not int or type(chunk) is not int
                or not 1 <= page <= 100 or not 0 <= chunk <= 99
                or not isinstance(text, str) or not 1 <= len(text.encode("utf-8")) <= 8000
                or (page, chunk) in rows):
            raise DemoError("The public report passages differ from the reviewed package.")
        rows[page, chunk] = text
    return _require_reviewed_passages(rows)


def _require_reviewed_passages(rows):
    payload = json.dumps([(p, c, text) for (p, c), text in sorted(rows.items())],
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(rows) != 54 or sha256(payload).hexdigest() != REVIEWED_SHA256:
        raise DemoError("The public report passages differ from the reviewed package.")
    return rows


@dataclass(frozen=True)
class Target:
    endpoint: str
    collection: str
    shared_read_only: bool = False

    def __post_init__(self):
        try:
            parsed = urlsplit(self.endpoint)
            host = parsed.hostname or ""
            allowed = (
                parsed.scheme == "https" and host.endswith(".zillizcloud.com")
                and all(re.fullmatch(r"[a-z0-9-]+", part) for part in host.split("."))
                and not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and parsed.path in {"", "/"}
                and parsed.port in {None, 443, 19530}
            )
        except ValueError:
            allowed = False
        if not allowed:
            raise DemoError("Use the approved Zilliz cluster's HTTPS endpoint with no credentials or path.")
        collection_pattern = NAMED_COLLECTION if self.shared_read_only else DEMO_COLLECTION
        if not collection_pattern.fullmatch(self.collection):
            raise DemoError("Supply an approved collection name, or the exact demo name printed by preview.")


class _LoopbackEmbedder(OllamaEmbeddingClient):
    """Reuse normalisation/batch behaviour but forbid redirects or proxy use."""
    def __init__(self):
        super().__init__(base_url=_OLLAMA, model="bge-m3", timeout=90)

    def _request(self, path, payload):
        import httpx
        try:
            with httpx.Client(timeout=httpx.Timeout(90, connect=4), trust_env=False,
                              follow_redirects=False) as client:
                response = client.post(self.base_url + path, json=payload)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise DemoError("Local Ollama embedding failed. Check that bge-m3 is installed and Ollama is running.") from None


def _check_vector(vector):
    if len(vector) != _DIMENSION or any(not isfinite(value) for value in vector):
        raise DemoError("Ollama returned an invalid bge-m3 vector.")
    return vector


def _connect(target, token):
    from pymilvus import MilvusClient
    # Dedicated secure connection; no global/default alias or tracked config.
    return MilvusClient(uri=target.endpoint, token=token, secure=True, dedicated=True, timeout=12)


def seed(target, token, rows, *, embedder=None, client_factory=None):
    """Only terminal seeding calls this function; it never writes an existing collection."""
    if target.shared_read_only:
        raise DemoError("A shared collection is read only; it cannot be seeded.")
    from pymilvus import DataType, MilvusClient
    embedder = embedder or _LoopbackEmbedder()
    client_factory = client_factory or _connect
    payload = []
    items = sorted(_require_reviewed_passages(rows).items())
    for offset in range(0, len(items), 8):
        batch = items[offset:offset + 8]
        vectors = embedder.embed_texts([text for _, text in batch])
        if len(vectors) != len(batch):
            raise DemoError("Ollama returned the wrong number of vectors; nothing was uploaded.")
        for ((page, chunk), text), vector in zip(batch, vectors):
            payload.append({
                "pk": f"p{page}_c{chunk}", "embedding": _check_vector(vector),
                "text_content": text, "source": SOURCE,
                "metadata": {"page_number": page, "chunk_index": chunk},
            })
    client = client_factory(target, token)
    try:
        if client.has_collection(target.collection, timeout=12):
            raise DemoError("The collection already exists. Preview a new name instead; no rows were written.")
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("pk", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=_DIMENSION)
        schema.add_field("text_content", DataType.VARCHAR, max_length=8192)
        schema.add_field("source", DataType.VARCHAR, max_length=512)
        schema.add_field("metadata", DataType.JSON)
        index = MilvusClient.prepare_index_params()
        index.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")
        client.create_collection(target.collection, schema=schema, index_params=index, timeout=60)
        # An uncertain write requires a new collection, not a retry into an existing one.
        added = client.insert(target.collection, payload, timeout=30)
        if added.get("insert_count") != len(payload):
            raise DemoError("The service did not confirm all rows. Do not demo this collection.")
        return len(payload)
    finally:
        client.close()


class _PinnedRetrieval:
    def __init__(self, client, target, rows):
        self.client, self.target, self.rows = client, target, rows

    def search_documents(self, *, embedData, limit, embedLimit, query, cshId,
                         isRunningUsingCshiId, isHybridSearchFlags):
        _check_vector(embedData)
        if isRunningUsingCshiId or isHybridSearchFlags:
            raise DemoError("Only the public dense-vector lookup is supported in this demo.")
        # Limit the provider request to the official document itself before the
        # independent passage-by-passage allowlist validation below.
        expr = "source == " + json.dumps(SOURCE)
        fields = ["text_content", "source", "metadata"]
        if self.target.shared_read_only:
            expr += ' and metadata["mongo_collection"] == "agriculture_documents"'
            fields = ["text_content", "source"]  # Never retrieve Mongo metadata/IDs as a separate field.
        matches = self.client.search(
            self.target.collection, data=[embedData], filter=expr, limit=limit,
            anns_field="embedding", search_params={"metric_type": "COSINE"},
            output_fields=fields, timeout=18, consistency_level="Strong",
        )
        results = []
        for hit in matches[0] if matches else []:
            field = hit.get("entity") or {}
            if field.get("source") != SOURCE:
                continue
            text = field.get("text_content")
            metadata = field.get("metadata") or {}
            if self.target.shared_read_only:
                # The old broad sync serializes a Mongo row into text_content.
                # Parse only the three known fields and ignore everything else.
                try:
                    public_row = json.loads(text)
                except (ValueError, TypeError):
                    continue
                if (not isinstance(public_row, dict) or public_row.get("source_file") != REPORT
                        or public_row.get("source_url") != SOURCE):
                    continue
                metadata, text = public_row, public_row.get("content")
            if not isinstance(metadata, dict):
                continue
            page, chunk = metadata.get("page_number"), metadata.get("chunk_index")
            if (type(page) is not int or type(chunk) is not int or not isinstance(text, str)
                    or self.rows.get((page, chunk)) != text):
                continue
            results.append({"text_content": text, "source": f"{SOURCE}#page={page}",
                            "metadata": {"page_number": page, "chunk_index": chunk},
                            "distance": hit.get("distance")})
        return results


def _chat_model():
    from langchain_ollama import ChatOllama
    return ChatOllama(model="qwen3:4b", base_url=_OLLAMA, temperature=0, reasoning=False,
                      num_ctx=4096, num_predict=250,
                      client_kwargs={"timeout": 80, "trust_env": False, "follow_redirects": False})


class PublicMilvusDemo:
    def __init__(self, target, token, *, rows=None, embedder=None, client_factory=None, model_factory=None):
        self.target = target
        self._token = token
        self._rows = public_passages() if rows is None else _require_reviewed_passages(rows)
        self._embedder = embedder or _LoopbackEmbedder()
        self._client_factory = client_factory or _connect
        self._model_factory = model_factory or _chat_model

    def ask(self, question, language):
        if language not in {"auto", "en"} or " ".join(question.split()).casefold().rstrip("?.") != QUESTION.casefold().rstrip("?"):
            raise ValueError("Milvus demo supports this public report question in English only: " + QUESTION)
        from node.retrieve_documents import RetrieveDocumentsNode
        from node.final_answer import FinalAnswerNode
        from services.dashboard_document_chat import _MARKER, _summary_status

        client = self._client_factory(self.target, self._token)
        try:
            if not client.has_collection(self.target.collection, timeout=12):
                raise DemoError("The approved Milvus collection was not found.")
            if not self.target.shared_read_only:
                client.load_collection(self.target.collection, timeout=25)
            # Shared collections must already be loaded by their owner; this
            # request path does not load, index, seed, delete or update them.
            node = RetrieveDocumentsNode(
                connector=_PinnedRetrieval(client, self.target, self._rows), embedder=self._embedder, top_k=6,
            )
            state = {"question": QUESTION, "subQuestions": [QUESTION]}
            evidence = node.retrieve_documents(state)["retrieved_documents"]
        finally:
            client.close()

        records = [{
            "citation_id": i, "source": SOURCE, "document_title": TITLE,
            **hit["metadata"], "content": hit["text_content"],
        } for i, hit in enumerate(evidence, 1)]
        for record, hit in zip(records, evidence):
            score = hit.get("distance")
            if type(score) in {int, float} and isfinite(score):
                record["cosine_score"] = round(float(score), 4)
        text, status = "No allowlisted report passages were returned by this Milvus collection.", "no_evidence"
        if records:
            text, status = ("Milvus returned the original passages below. No verified generated summary is available.",
                            "evidence_only")
            try:
                from langsmith import tracing_context
                with tracing_context(enabled=False):
                    generated = FinalAnswerNode(self._model_factory()).generate_final_answer({
                        **state, "retrieved_documents": evidence,
                    })["answer"]
            except Exception:
                generated = ""
            cited = {int(v) for group in _MARKER.findall(generated) for v in group.split(",")}
            support = [record for record in records if record["citation_id"] in cited]
            if cited == {row["citation_id"] for row in support} and support and (
                _summary_status(generated, "en", support) == "accepted"
            ):
                text, status = generated, "cited"
        return {
            "answer": text, "answer_language": "en", "intent": "milvus_vector_rag",
            "model": "bge-m3 + local Ollama · public report only",
            "filters": {"collection": self.target.collection},
            "retrieval": {"mode": "milvus_dense_cosine"},
            "sources": [{k: v for k, v in record.items() if k != "content"} for record in records],
            "records": records, "document_chat": {"status": status, "searches": [QUESTION]},
        }
