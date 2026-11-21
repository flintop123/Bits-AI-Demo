"""Optional LangGraph QA over the separately reviewed Milvus corpus."""

import re

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agent_config import get_chat_model
from graphstate import ChatState
from node.final_answer import FinalAnswerNode
from node.generate_questions import GenerateQuestionsNode
from node.greeting_response import GreetingResponseNode
from node.retrieve_documents import RetrieveDocumentsNode


class RagModel:
    def __init__(self, config, model=None, checkpointer=None, retriever_node=None, *, stateless=False):
        model = model if model is not None else get_chat_model()
        graph = StateGraph(ChatState)
        graph.add_node("greeting_response", GreetingResponseNode().respond)
        graph.add_node("generate_questions", GenerateQuestionsNode(model).generate_sub_questions)
        retriever = retriever_node if retriever_node is not None else RetrieveDocumentsNode(config)
        graph.add_node("retrieve_documents", retriever.retrieve_documents)
        graph.add_node("final_answer", FinalAnswerNode(model, config).generate_final_answer)
        graph.set_conditional_entry_point(
            self.route_question, {"greeting_response": "greeting_response", "generate_questions": "generate_questions"},
        )
        graph.add_edge("greeting_response", END)
        graph.add_edge("generate_questions", "retrieve_documents")
        graph.add_edge("retrieve_documents", "final_answer")
        graph.add_edge("final_answer", END)
        if not stateless and checkpointer is None:
            checkpointer = MemorySaver()
        self.runnable = graph.compile(checkpointer=checkpointer)

    @staticmethod
    def route_question(state):
        normalized = re.sub(r"[!?,.;:।]+$", "", str(state.get("question", "")).casefold().strip()).strip()
        greetings = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening",
                     "namaste", "नमस्ते", "नमस्कार", "प्रणाम"}
        return "greeting_response" if not normalized or normalized in greetings else "generate_questions"
