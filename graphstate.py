from typing import TypedDict

from tools.api_extractor.document import Documents


class ChatState(TypedDict, total=False):
    question: str
    reformulated_question: str
    cshId: str
    isRunningUsingCshiId: bool
    subQuestions: list[str]
    embeddings: list[list[float]]
    source: list[str]
    messages: list[dict[str, str]]
    answer: str
    title: str
    documents: list[Documents]
    intent: str
    retrieved_documents: list[dict[str, object]]
