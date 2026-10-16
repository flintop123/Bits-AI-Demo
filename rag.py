from langchain_core.output_parsers import StrOutputParser
from conn.milvusDbConnector import RecZillizVector
from langchain.prompts import ChatPromptTemplate
from prompts.prompts import get_title_prompt, get_reformulated_question_prompt
from langgraph.graph import StateGraph, END
from langchain_core.messages import trim_messages


from conn.mongodb import BiharCropMongo
from graphstate import ChatState


class RagModel:
    def __init__(self, config):
        self.config = config
        self.graph = StateGraph(ChatState)
        #self.checkpointer = BiharCropMongo().getMongoDBSaverCheckpointer()
        #self.runnable = self.compileGraph()
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
    
     
    def setup_graph(self):
        self.graph.add_node("readMundiData", self.readMundiDataInstance.readAndWriteData)
        self.graph.add_node("writeMundiData", self.writeMundiDataInstance.writeMundiData)
       
        
        self.graph.set_entry_point("readMundiData")
        
        self.graph.add_edge("readMundiData", "writeMundiData")
        self.graph.add_edge("writeMundiData", "END")
        return self.graph

    def compileGraph(self):
        graph = self.setup_graph()
        runnable = graph.compile(checkpointer=self.checkpointer)
        return runnable