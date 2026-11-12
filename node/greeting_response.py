"""Return a short localized response for greeting-only inputs."""

from graphstate import ChatState


class GreetingResponseNode:
    def respond(self, state: ChatState):
        question = str(state.get("question", ""))
        if any("\u0900" <= character <= "\u097f" for character in question):
            answer = (
                "नमस्ते! मैं बिहार कृषि सहायक हूँ। "
                "कृषि से जुड़ा कोई प्रश्न पूछें।"
            )
        else:
            answer = (
                "Hello! I can help with Bihar agriculture. "
                "What would you like to know?"
            )
        return {
            "intent": "greeting",
            "answer": answer,
            "subQuestions": [],
            "source": [],
            "title": "",
        }
