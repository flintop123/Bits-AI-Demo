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
from ingest_any_source import ingest_api_urls, ingest_pdf
from sync_mongodb_to_milvus import sync_mongodb_to_milvus


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

        # Previous mandi-only implementation retained for reference:
        # documents = ReadMundiData().load_bihar_krishi_mandi_pages(self.config.get("bihar_krishi").get("urls"))
        # isWritten = BiharCropMongo().write_mandi_records(documents, source_url=self.config.get("bihar_krishi").get("urls")[0],)
        # if isWritten == 0:
        #     logger.info("All records were written to MongoDB.")
        # logger.info("********")
        
        ingestion = self.config.get("document_ingestion", {})

        # for pdf_path in ingestion.get("pdf_paths", []):
        #     summary = ingest_pdf(
        #         pdf_path,
        #         force_ocr=ingestion.get("force_ocr", False),
        #         ocr_enabled=ingestion.get("ocr_enabled", True),
        #     )
        #     logger.info(f"PDF ingestion completed: {summary}")

        # api_urls = ingestion.get("api_urls", [])
        # if api_urls:
        #     summary = ingest_api_urls(
        #         api_urls,
        #         headers=ingestion.get("api_headers"),
        #         timeout_ms=ingestion.get("api_timeout_ms", 60000),
        #     )
        #     logger.info(f"Generic API ingestion completed: {summary}")

        # if ingestion.get("run_mandi_ingestion", True):
        #     mandi_urls = self.config.get("bihar_krishi", {}).get("urls", [])
        #     if mandi_urls:
        #         documents = ReadMundiData().load_bihar_krishi_mandi_pages(
        #             mandi_urls
        #         )
        #         database = BiharCropMongo()
        #         try:
        #             for index, document in enumerate(documents):
        #                 source_url = (
        #                     getattr(document, "source", None)
        #                     or document.metadata.get("source")
        #                     or mandi_urls[min(index, len(mandi_urls) - 1)]
        #                 )
        #                 inserted = database.write_mandi_records(
        #                     [document],
        #                     source_url=source_url,
        #                 )
        #                 logger.info(
        #                     f"Mandi data from {source_url}: {inserted} "
        #                     "new record(s)"
        #                 )
        #         finally:
        #             database.client.close()

        if ingestion.get("sync_mongodb_to_milvus", False):
            summary = sync_mongodb_to_milvus(self.config)
            logger.info(f"MongoDB to Milvus sync completed: {summary}")
        logger.info("Data ingestion finished.")

''' This metod is right now not using, but we will once we will write all different types of data.'''
@app.route("/bihar-crop-chatbot/ask", methods=["GET"])
def ask_question():

    question = request.args.get("question", "")
    thread_id = request.headers.get("X-Thread-ID")
    if not thread_id:
        thread_id = str(uuid.uuid4())

    try:
        threadConfig = {"configurable": {"thread_id": thread_id}}

        run_id = uuid.uuid4()
        result = ragAgent.runnable.invoke(
            {"question": question.strip()},
            config=threadConfig,
        )
        
        return jsonify({
            "answer": result.get("answer", ""),
            "questions": result.get("subQuestions", []),
            "source": result.get("source", []),
            "thread_id": thread_id,
            "title": result.get("title", ""),
            "run_id": run_id
            })

    except Exception as e:
        logger.error(f"Error occurred: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500



def run_app():
    qa_enabled = config.get("retriever", {}).get("qa_enabled", False)
    if qa_enabled:
        logger.info("Starting the Bihar Crop Chatbot API server...")
        app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
    else:
        logger.info("QA is disabled in the configuration. Skipping API server startup.")
        InsertTheBiharKrishiData().readAndWriteData()
    # app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
    #app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

if __name__ == "__main__":
    run_app()