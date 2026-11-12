"""Generate a grounded answer from retrieved Milvus evidence."""

from langchain_core.prompts import ChatPromptTemplate

from agent_config import get_chat_model
from graphstate import ChatState


class FinalAnswerNode:
    def __init__(self, model=None):
        self.model = model or get_chat_model()
        self.prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "Answer the user's original question using only the supplied "
                "retrieved evidence. Do not invent facts. Cite supporting "
                "evidence inline using its bracketed source number, such as "
                "[1]. If the evidence does not answer the question, state "
                "what is missing. Respond in the same language as the user.",
            ),
            (
                "human",
                "Original question:\n{question}\n\n"
                "Generated subquestions:\n{subquestions}\n\n"
                "Retrieved evidence:\n{context}",
            ),
        ])

    def generate_final_answer(self, state: ChatState):
        documents = state.get("retrieved_documents", [])
        if not documents:
            return {
                "answer": (
                    "I couldn't find relevant information in the Milvus "
                    "collection to answer this. Please try rephrasing your "
                    "question."
                ),
                "source": [],
            }

        sources = []
        context_parts = []
        for index, document in enumerate(documents, start=1):
            source = document.get("source") or "Milvus"
            if source not in sources:
                sources.append(source)
            context_parts.append(
                f"[{index}] Source: {source}\n"
                f"{document['text_content']}"
            )

        messages = self.prompt.format_messages(
            question=state.get("question", ""),
            subquestions="\n".join(
                f"- {question}"
                for question in state.get("subQuestions", [])
            ),
            context="\n\n".join(context_parts),
        )
        response = self.model.invoke(messages)
        answer = getattr(response, "content", response)
        if isinstance(answer, list):
            answer = "\n".join(
                str(part.get("text", ""))
                for part in answer
                if isinstance(part, dict)
            )
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("The answer model returned empty content")

        return {
            "answer": answer.strip(),
            "source": sources,
        }
