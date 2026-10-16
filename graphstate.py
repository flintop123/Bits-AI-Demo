from uuid import UUID

from xmlrpc.client import boolean

from tools.api_extractor.document import Documents
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage
from pydantic import BaseModel, Field
from typing import List, Literal, Union

class ChatState(TypedDict):
    question : str
    reformulated_question: str
    cshId : str
    isRunningUsingCshiId : bool
    subQuestions : list[str]
    embeddings : list[list[float]]
    source : list[str]
    messages: list[dict[str, str]]
    answer: str
    title : str
    documents : list[Documents]
