from envsetup import setUpEnvVar
from config_reader import read_config
from conn.milvusDbConnector import RecZillizVector
from flask import Flask, request, jsonify
from loghandler import getLogger
from conn.mongodb import BiharCropMongo

import uuid
from langsmith import Client
from langgraph.types import Command
from rag import RagModel
from conn.mongodb import BiharCropMongo
from tools.api_extractor.readMundiDatas import ReadMundiData
import asyncio


client = Client()

app = Flask(__name__)

setUpEnvVar()
logger = getLogger()
config = read_config()
ragAgent = RagModel(config=config)

class InsertTheBiharKrishiData:
    def __init__(self) -> None:
        self.config = config
        
    def readAndWriteData(self):
        logger.info(f"This is the defined config : {self.config}")
        documents = ReadMundiData().load_bihar_krishi_mandi_pages(self.config.get("bihar_krishi").get("urls"))
        isWritten =  BiharCropMongo().write_mandi_records(documents, source_url=self.config.get("bihar_krishi").get("urls")[0])
        if isWritten == 0:
            logger.info("All records were written to MongoDB.")
        logger.info("********")

@app.route("/bihar-crop-chatbot/ask", methods=["GET"])
def ask_question():

    question = request.args.get("question", "")
    thread_id = request.headers.get("X-Thread-ID")
    title = ""
    if not thread_id:
        thread_id = str(uuid.uuid4())

    try:
        threadConfig = {"configurable": {"thread_id": thread_id}}

        run_id = uuid.uuid4()
        result = ragAgent.runnable.invoke(
            {"input": question.strip(),"question": question.strip(),  "session_id": thread_id},
                config=threadConfig, stream_mode="values"
        )
        
        return jsonify({
            "answer": result['answer'],
            "source": result['source'],
            "thread_id": thread_id,
            "title": result['title'],
            "run_id": run_id
            })

    except Exception as e:
        logger.error(f"Error occurred: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500



def run_app():
    InsertTheBiharKrishiData().readAndWriteData()
    #app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

if __name__ == "__main__":
    run_app()