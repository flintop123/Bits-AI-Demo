from langchain_milvus import Milvus

from config_reader import read_config
from model import Model
from pymilvus import connections, utility, Collection

from loghandler import getLogger
import re
from pymilvus import AnnSearchRequest
from pymilvus import RRFRanker

class RecZillizVector:
    
    def __init__(self):
        self.logger = getLogger()
        self.config = read_config().get("milvus")

    async def getMilvusVector(self, model: Model):
        # Initialize ZillizVector store
        vector_store = Milvus(
        embedding_function=model.getTheEmbeddingModels(),
        connection_args= {
            "uri": self.config.get("zilliz_uri"),
            "token": self.config.get("zilliz_token"),
            "secure": True
        },
        collection_name=self.config.get("collectionName")
        )
        return vector_store

    def getOrCreateTheCollection(self):
        collectionName = self.config.get("collectionName") 
        if utility.has_collection(collectionName):
            collection = Collection(collectionName)
            return collection
        else:
            raise ValueError(f"Collection '{collectionName}' does not exist. Please create it first.")
    
    def connect(self):
        # Here you would implement the actual connection logic to Zilliz Vector DB
        #print(f"Connecting to Zilliz Vector DB at {self.host}:{self.port} as {self.user}")
        ZILLIZ_URI = ""
        ZILLIZ_TOKEN = ""

        # Connect
        connections.connect(
            alias="default",
            uri= self.config.get("zilliz_uri", ZILLIZ_URI),  # Use provided URI or default
            token= self.config.get("zilliz_token", ZILLIZ_TOKEN),  # Use provided token or default
            secure=True  # SSL encryption enabled (important)
       )     

    def search_documents(self, embedData, limit, embedLimit, query, cshId, isRunningUsingCshiId, isHybridSearchFlags):
        """
        Search for documents in the Milvus collection based on a query embedding.

        Args:
            query_embedding (list): Vector embedding of the query
            limit (int): Number of results to return

        Returns:
            list: List of matching documents
        """
        collection = self.getOrCreateTheCollection()
        
        # Perform search
        search_params = {
            "metric_type": "COSINE",
            "params": {"nprobe": 10}
        }

        expr = None
        
        dense_req = AnnSearchRequest(
            data=[embedData],
            anns_field='embedding',
            param=search_params,
            limit=limit,
            expr= expr
        )

        sparse_req = AnnSearchRequest(
            data=[query],
            anns_field="sparse_vector",
            param={"metric_type": "BM25"},
            limit=limit,
            expr= expr
        )

        if isHybridSearchFlags:
            results = collection.hybrid_search(
                reqs=[dense_req, sparse_req],
                rerank=RRFRanker(),
                limit=limit,
                #expr= expr,
                output_fields=["text_content", "source", "metadata"]
            )

        #It will be used to find the best sources based on the embedding similarity, As Hybrid serch reranking doesn't find the best sources.
        if not isHybridSearchFlags:
            results = collection.search(
                data=[embedData],
                anns_field='embedding',
                param=search_params,
                limit=embedLimit,
                expr= expr,
                output_fields=["text_content", "source", "metadata"]
            )

        enriched_results = []
        for hit in results[0]:
            enriched_results.append({
                "query": query,
                #"distance": hit.data.get("distance"),
                "distance": getattr(hit, "distance", None),
                "text_content": hit.entity.get("text_content"),
                "source": hit.entity.get("source"),
                "metadata": hit.entity.get("metadata")
        })


        return enriched_results