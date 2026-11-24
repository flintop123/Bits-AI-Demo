"""Dense read-only retrieval from a reviewed product corpus."""

import os
from uuid import uuid4

from pymilvus import Collection, connections, utility

from config_reader import read_config
from sync_mongodb_to_milvus import COLLECTION_NAME, milvus_settings


class RecZillizVector:
    def __init__(self, config=None):
        self.config = read_config() if config is None else config
        self.alias = f"agri_qa_{uuid4().hex}"
        self.collection = None

    def connect(self):
        name = os.getenv("AGRI_MILVUS_COLLECTION") or self.config.get("milvus", {}).get("collectionName", "")
        if not COLLECTION_NAME.fullmatch(name):
            raise ValueError("Select a reviewed Milvus corpus in AGRI_MILVUS_COLLECTION")
        settings, _ = milvus_settings(self.config)
        connections.connect(alias=self.alias, timeout=10, **settings)
        try:
            if not utility.has_collection(name, using=self.alias, timeout=5):
                raise ValueError("Configured Milvus corpus does not exist")
            if getattr(utility.load_state(name, using=self.alias, timeout=5), "name", "") != "Loaded":
                raise ValueError("Configured corpus is not loaded; complete and verify the index build")
            self.collection = Collection(name, using=self.alias)
        except Exception:
            connections.disconnect(self.alias)
            raise

    def close(self):
        connections.disconnect(self.alias)
        self.collection = None

    def search_documents(self, *, embedData, limit, query, model, **_):
        if self.collection is None:
            raise RuntimeError("Connect to a reviewed corpus before searching")
        hits = self.collection.search(
            data=[embedData], anns_field="embedding", param={"metric_type": "COSINE", "params": {}},
            limit=limit, expr="metadata[\"embedding_model\"] == {embedding_model}",
            expr_params={"embedding_model": model}, timeout=8,
            output_fields=["text_content", "source", "metadata"],
        )
        return [{
            "query": query, "distance": hit.distance,
            "text_content": hit.entity.get("text_content"),
            "source": hit.entity.get("source"), "metadata": hit.entity.get("metadata"),
        } for hit in hits[0]] if hits else []
