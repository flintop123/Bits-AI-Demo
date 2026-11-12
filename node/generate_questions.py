"""Generate four distinct follow-up questions from a user prompt."""

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, field_validator

from agent_config import get_chat_model
from graphstate import ChatState


class QuestionSuggestions(BaseModel):
    questions: list[str] = Field(min_length=4, max_length=4)

    @field_validator("questions")
    @classmethod
    def require_four_distinct_questions(cls, questions):
        cleaned = [question.strip() for question in questions]
        if any(not question for question in cleaned):
            raise ValueError("Questions must not be empty")
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
        result = self.structured_model.invoke(messages)
        suggestions = QuestionSuggestions.model_validate(result).questions
        answer = "Here are four questions you could explore:\n" + "\n".join(
            f"{index}. {suggestion}"
            for index, suggestion in enumerate(suggestions, start=1)
        )
        return {
            "intent": "generate_questions",
            "answer": answer,
            "subQuestions": suggestions,
            "source": [],
            "title": "",
        }
