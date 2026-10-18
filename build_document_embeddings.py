"""Build or refresh multilingual embeddings for stored PDF chunks."""

import argparse
import os
import sys
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne

from services.ollama_embedding_client import OllamaEmbeddingClient


class DocumentEmbeddingIndexer:
    def __init__(self, collection, embedder=None):
        self.collection = collection
        self.embedder = embedder or OllamaEmbeddingClient()

    def run(self, *, rebuild=False, batch_size=8):
        if batch_size < 1 or batch_size > 64:
            raise ValueError("batch size must be between 1 and 64")
        records = list(self.collection.find(
            {"content": {"$type": "string"}},
            {
                "content": 1,
                "document_title": 1,
                "content_hash": 1,
                "embedding": 1,
                "embedding_model": 1,
                "embedding_content_hash": 1,
            },
        ))
        selected = [
            record for record in records
            if rebuild or self._needs_embedding(record)
        ]
        embedded = 0
        dimension = None
        for start in range(0, len(selected), batch_size):
            batch = selected[start:start + batch_size]
            texts = [self._embedding_text(record) for record in batch]
            vectors = self.embedder.embed_texts(texts)
            now = datetime.now(timezone.utc)
            operations = []
            for record, vector in zip(batch, vectors):
                dimension = len(vector)
                operations.append(UpdateOne(
                    {"_id": record["_id"]},
                    {"$set": {
                        "embedding": vector,
                        "embedding_model": self.embedder.model,
                        "embedding_dimension": dimension,
                        "embedding_content_hash": record.get("content_hash"),
                        "embedded_at": now,
                    }},
                ))
            if operations:
                self.collection.bulk_write(operations, ordered=False)
                embedded += len(operations)
        self.collection.create_index(
            [("embedding_model", 1)], name="document_embedding_model"
        )
        return {
            "model": self.embedder.model,
            "documents_total": len(records),
            "documents_selected": len(selected),
            "documents_embedded": embedded,
            "documents_current": len(records) - len(selected),
            "dimension": dimension or self._existing_dimension(records),
        }

    def _needs_embedding(self, record):
        embedding = record.get("embedding")
        return (
            record.get("embedding_model") != self.embedder.model
            or record.get("embedding_content_hash") != record.get("content_hash")
            or not isinstance(embedding, list)
            or not embedding
        )

    @staticmethod
    def _embedding_text(record):
        title = str(record.get("document_title") or "").strip()
        content = str(record.get("content") or "").strip()
        return f"{title}\n{content}" if title else content

    @staticmethod
    def _existing_dimension(records):
        for record in records:
            embedding = record.get("embedding")
            if isinstance(embedding, list) and embedding:
                return len(embedding)
        return None


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--batch-size", type=int, default=8)
    return parser.parse_args(argv)


def main(argv=None):
    client = None
    try:
        args = parse_args(argv)
        uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        client = MongoClient(uri)
        client.admin.command("ping")
        collection = client["bihar_agriculture"]["agriculture_documents"]
        summary = DocumentEmbeddingIndexer(collection).run(
            rebuild=args.rebuild,
            batch_size=args.batch_size,
        )
        print("\nPhase 3 document embedding summary")
        print("----------------------------------")
        print(f"Model: {summary['model']}")
        print(f"Documents stored: {summary['documents_total']}")
        print(f"Documents selected: {summary['documents_selected']}")
        print(f"Documents embedded: {summary['documents_embedded']}")
        print(f"Already current: {summary['documents_current']}")
        print(f"Embedding dimension: {summary['dimension']}")
        return 0
    except Exception as exc:
        print(f"Embedding build failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
