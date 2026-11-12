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
        retrieval_config = self.config.get("retrieval", {})
        self.top_k = int(top_k or retrieval_config.get("top_k", 3))
        if self.top_k < 1:
            raise ValueError("top_k must be at least 1")
        self.hybrid_search = bool(
            retrieval_config.get("hybrid_search", False)
        )

    def retrieve_documents(self, state: ChatState):
        questions = state.get("subQuestions", [])
        if not questions:
            raise ValueError("Question generation returned no subquestions")

        connector = self.connector
        if connector is None:
            connector = RecZillizVector()
            connector.connect()
            self.connector = connector

        results = []
        seen = set()
        for subquestion in questions:
            embedding = self.embedder.embed_query(subquestion)
            matches = connector.search_documents(
                embedData=embedding,
                limit=self.top_k,
                embedLimit=self.top_k,
                query=subquestion,
                cshId=state.get("cshId", ""),
                isRunningUsingCshiId=state.get(
                    "isRunningUsingCshiId",
                    False,
                ),
                isHybridSearchFlags=self.hybrid_search,
            )
            for match in matches:
                text = str(match.get("text_content") or "").strip()
                if not text:
                    continue
                metadata = match.get("metadata") or {}
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
                    "distance": match.get("distance"),
                })

        return {"retrieved_documents": results}
