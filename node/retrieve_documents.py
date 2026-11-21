"""Retrieve Milvus evidence for each generated subquestion."""

from conn.milvusDbConnector import RecZillizVector
from graphstate import ChatState
from services.ollama_embedding_client import OllamaEmbeddingClient


class RetrieveDocumentsNode:
    def __init__(
        self,
        config=None,
        *,
        connector=None,
        embedder=None,
        top_k=None,
    ):
        self.config = config or {}
        self.connector = connector
        self.embedder = embedder or OllamaEmbeddingClient()
        retrieval_config = self.config.get("retriever", {})
        self.top_k = int(top_k or retrieval_config.get("top_k", 3))
        if not 1 <= self.top_k <= 8:
            raise ValueError("top_k must be 1–8")
        self.minimum_similarity = float(retrieval_config.get("minimum_similarity", 0.45))
        if not 0 <= self.minimum_similarity <= 1:
            raise ValueError("minimum_similarity must be between 0 and 1")

    def retrieve_documents(self, state: ChatState):
        primary = str(state.get("question", "")).strip()
        questions = list(dict.fromkeys(filter(None, [primary, *state.get("subQuestions", [])[:4]])))
        if not questions:
            raise ValueError("Question generation returned no subquestions")

        connector = self.connector or RecZillizVector(self.config)
        try:
            if self.connector is None:
                connector.connect()
            return self._search(questions, connector)
        finally:
            if self.connector is None and connector.collection is not None:
                connector.close()

    def _search(self, questions, connector):

        results = []
        seen = set()
        for subquestion in questions:
            embedding = self.embedder.embed_query(subquestion)
            matches = connector.search_documents(
                embedData=embedding,
                limit=self.top_k,
                query=subquestion,
                model=getattr(self.embedder, "model", ""),
            )
            for match in matches:
                text = str(match.get("text_content") or "").strip()
                if not text:
                    continue
                metadata = match.get("metadata") or {}
                distance = match.get("distance")
                if not isinstance(metadata, dict) or not isinstance(distance, (int, float)) or not (
                    self.minimum_similarity <= distance <= 1.000001
                ):
                    continue
                source = (
                    match.get("source")
                    or metadata.get("source_url")
                    or metadata.get("source")
                    or "Milvus"
                )
                identity = (str(source), text)
                if identity in seen:
                    continue
                seen.add(identity)
                results.append({
                    "query": subquestion,
                    "text_content": text,
                    "source": str(source),
                    "metadata": metadata,
                    "distance": distance,
                })
        # Keep initial direct-query matches first, then order supplementary evidence.
        results.sort(key=lambda row: (row["query"] != questions[0], -row["distance"]))
        return {"retrieved_documents": results[:12]}
