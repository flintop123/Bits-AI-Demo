import unittest

from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage

from node.retrieve_documents import RetrieveDocumentsNode
from rag import RagModel


class FakeStructuredModel:
    def invoke(self, messages):
        return {
            "questions": [
                "How does rainfall affect this crop?",
                "Which markets report its prices?",
                "What are its seasonal trends?",
                "Which practices can improve its yield?",
            ]
        }


class FakeChatModel:
    def with_structured_output(self, schema):
        self.output_schema = schema
        return FakeStructuredModel()

    def invoke(self, messages):
        self.last_messages = messages
        return AIMessage(content="The retrieved evidence supports this answer [1].")


class FakeRetrieverNode:
    def __init__(self):
        self.called = False

    def retrieve_documents(self, state):
        self.called = True
        self.questions = state["subQuestions"]
        return {
            "retrieved_documents": [{
                "query": state["subQuestions"][0],
                "text_content": "Verified crop-price evidence.",
                "source": "https://example.test/mandi",
                "metadata": {},
                "distance": 0.1,
            }]
        }


class FakeEmbeddingClient:
    def __init__(self):
        self.queries = []

    def embed_query(self, query):
        self.queries.append(query)
        return [0.1, 0.2]


class FakeMilvusConnector:
    def __init__(self):
        self.queries = []

    def search_documents(self, **kwargs):
        self.queries.append(kwargs["query"])
        return [{
            "text_content": "Matching Milvus evidence",
            "source": "https://example.test/source",
            "metadata": {},
            "distance": 0.2,
        }]


class RagWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.model = FakeChatModel()
        self.retriever_node = FakeRetrieverNode()
        self.rag = RagModel(
            config={},
            model=self.model,
            checkpointer=MemorySaver(),
            retriever_node=self.retriever_node,
        )

    def test_greeting_is_routed_to_greeting_node_and_checkpointed(self):
        config = {"configurable": {"thread_id": "greeting-thread"}}

        result = self.rag.runnable.invoke(
            {"question": "Hello!"},
            config=config,
        )

        self.assertEqual(result["intent"], "greeting")
        self.assertEqual(result["subQuestions"], [])
        self.assertIn("Hello", result["answer"])
        self.assertFalse(self.retriever_node.called)
        checkpoint = self.rag.runnable.get_state(config)
        self.assertEqual(checkpoint.values["intent"], "greeting")

    def test_non_greeting_retrieves_for_four_questions_then_answers(self):
        result = self.rag.runnable.invoke(
            {"question": "Tell me about crop prices"},
            config={"configurable": {"thread_id": "question-thread"}},
        )

        self.assertEqual(result["intent"], "generate_questions")
        self.assertEqual(len(result["subQuestions"]), 4)
        self.assertEqual(len(self.retriever_node.questions), 4)
        self.assertTrue(self.retriever_node.called)
        self.assertIn("retrieved evidence", result["answer"])
        self.assertEqual(
            result["source"],
            ["https://example.test/mandi"],
        )
        self.assertIn(
            "Verified crop-price evidence.",
            str(self.model.last_messages),
        )

    def test_hindi_greeting_gets_hindi_response(self):
        result = self.rag.runnable.invoke(
            {"question": "नमस्ते"},
            config={"configurable": {"thread_id": "hindi-thread"}},
        )

        self.assertEqual(result["intent"], "greeting")
        self.assertIn("नमस्ते", result["answer"])

    def test_empty_input_routes_to_greeting_prompt(self):
        result = self.rag.runnable.invoke(
            {"question": ""},
            config={"configurable": {"thread_id": "empty-thread"}},
        )

        self.assertEqual(result["intent"], "greeting")
        self.assertEqual(result["subQuestions"], [])

    def test_retriever_queries_milvus_for_each_subquestion(self):
        connector = FakeMilvusConnector()
        embedder = FakeEmbeddingClient()
        node = RetrieveDocumentsNode(
            connector=connector,
            embedder=embedder,
            top_k=2,
        )
        subquestions = ["question one", "question two", "question three", "question four"]

        result = node.retrieve_documents({
            "question": "original question",
            "subQuestions": subquestions,
        })

        self.assertEqual(connector.queries, subquestions)
        self.assertEqual(embedder.queries, subquestions)
        self.assertEqual(len(result["retrieved_documents"]), 1)
        self.assertEqual(
            result["retrieved_documents"][0]["text_content"],
            "Matching Milvus evidence",
        )


if __name__ == "__main__":
    unittest.main()
