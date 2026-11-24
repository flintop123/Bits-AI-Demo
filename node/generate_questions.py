"""Generate four distinct follow-up questions from a user prompt."""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, Field, field_validator

from agent_config import get_chat_model
from graphstate import ChatState


class QuestionSuggestions(BaseModel):
    questions: list[str] = Field(min_length=4, max_length=4)

    @field_validator("questions")
    @classmethod
    def require_four_distinct_questions(cls, questions):
        cleaned = [question.strip() for question in questions]
        if any(not 1 <= len(question) <= 250 for question in cleaned):
            raise ValueError("Follow-ups must be 1–250 characters")
        if len({question.casefold() for question in cleaned}) != 4:
            raise ValueError("The four questions must be distinct")
        return cleaned


class GenerateQuestionsNode:
    def __init__(self, model=None):
        self.model = model or get_chat_model()
        self.structured_model = self.model.with_structured_output(
            QuestionSuggestions
        )
        self.prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "Generate exactly four different, useful follow-up questions "
                "based on the user's input. Do not answer the input. Keep "
                "questions relevant to Bihar agriculture when appropriate. "
                "Use the same language as the user's input. Return only the "
                "requested structured result.",
            ),
            ("human", "{question}"),
        ])

    def generate_sub_questions(self, state: ChatState):
        question = str(state.get("question", "")).strip()
        if not question:
            raise ValueError("A non-empty question is required")

        messages = self.prompt.format_messages(question=question)
        try:
            result = self.structured_model.invoke(messages)
            suggestions = QuestionSuggestions.model_validate(result).questions
        except (ValueError, OutputParserException):
            # The original question still supplies the primary retrieval query.
            suggestions = []
        return {
            "intent": "generate_questions",
            "answer": "",
            "subQuestions": suggestions,
            "source": [],
            "title": "",
        }
