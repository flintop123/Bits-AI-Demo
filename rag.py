import re

from langchain_core.output_parsers import StrOutputParser
from conn.milvusDbConnector import RecZillizVector
# from langchain.prompts import ChatPromptTemplate
from langchain_core.prompts import ChatPromptTemplate#
from prompts.prompts import get_title_prompt, get_reformulated_question_prompt
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import trim_messages


from conn.mongodb import BiharCropMongo
from graphstate import ChatState
from agent_config import get_chat_model
from node.greeting_response import GreetingResponseNode
from node.generate_questions import GenerateQuestionsNode
from node.retrieve_documents import RetrieveDocumentsNode
from node.final_answer import FinalAnswerNode


class RagModel:
    def __init__(
        self,
        config,
        model=None,
        checkpointer=None,
        retriever_node=None,
    ):
        self.config = config
        self.model = model or get_chat_model()
        self.checkpointer = (
            checkpointer if checkpointer is not None else MemorySaver()
        )
        self.graph = StateGraph(ChatState)
        self.greeting_response_node = GreetingResponseNode()
        self.generate_questions_node = GenerateQuestionsNode(self.model)
        self.retrieve_documents_node = (
            retriever_node or RetrieveDocumentsNode(config)
        )
        self.final_answer_node = FinalAnswerNode(self.model)
        self.runnable = self.compileGraph()
        #self.recZillizVector = RecZillizVector()
        # Connect to Zilliz Vector DB in a singelton manner by maintaining a single connection by alias
        #self.recZillizVector.connect()
        

    def messages_to_dicts(self, messages):
        return [{"role": msg.type, "content": msg.content} for msg in messages]

    def generate_title(self, input: dict):
        #llm = self.model.getTheChatMiniModels()
        title_prompt = ChatPromptTemplate.from_template(get_title_prompt())
        title_chain = (
            title_prompt
            #| llm
            | StrOutputParser()
        )
        output = title_chain.with_config({"run_name": input.get("user_id", "generate Title")}).invoke({"question": input.get("question", "")})
        if not output:
            return ""
        return output.strip().lower()

    def handle_unknown_input(self, state: ChatState):
        answer = "🤔 I'm not sure how to help with that. Please ask a question related to Algonomy."
        messages = state.get("messages", [])
        title = state.get("title", "")

        #converting it into dict form to allow serialization while checkpointing HumanMessage and AIMessage not serializable directly
        dict_form_msg = self.messages_to_dicts(messages)

        messages.clear()
        return {
            "answer": answer,
            "source": [],
            "messages": dict_form_msg,
            "title": state.get("title", "")
        }
    
    @staticmethod
    def route_question(state: ChatState):
        question = str(state.get("question", "")).casefold().strip()
        normalized = re.sub(r"[!?,.;:]+$", "", question).strip()
        greetings = {
            "hi",
            "hello",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
            "namaste",
            "नमस्ते",
            "नमस्कार",
            "प्रणाम",
        }
        return (
            "greeting_response"
            if not normalized or normalized in greetings
            else "generate_questions"
        )
     
    def setup_graph(self):
        self.graph.add_node(
            "greeting_response",
            self.greeting_response_node.respond,
        )
        self.graph.add_node(
            "generate_questions",
            self.generate_questions_node.generate_sub_questions,
        )
        self.graph.add_node(
            "retrieve_documents",
            self.retrieve_documents_node.retrieve_documents,
        )
        self.graph.add_node(
            "final_answer",
            self.final_answer_node.generate_final_answer,
        )
        self.graph.set_conditional_entry_point(
            self.route_question,
            {
                "greeting_response": "greeting_response",
                "generate_questions": "generate_questions",
            },
        )
        self.graph.add_edge("greeting_response", END)
        self.graph.add_edge("generate_questions", "retrieve_documents")
        self.graph.add_edge("retrieve_documents", "final_answer")
        self.graph.add_edge("final_answer", END)
        return self.graph

    def compileGraph(self):
        graph = self.setup_graph()
        runnable = graph.compile(checkpointer=self.checkpointer)
        return runnable