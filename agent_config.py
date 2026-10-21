"""Single configuration point for the LangChain ReAct agent.

``agent.py`` and every ``@tool`` wrapper under ``agent_tools/`` read the
Ollama model and MongoDB connection from this one file instead of each
reading ``os.environ`` separately.

This intentionally reuses the exact environment variable names already read
by ``services/ollama_client.py``, ``services/ollama_embedding_client.py``,
and the ``conn/*.py`` MongoDB connectors. Those existing modules are not
imported or changed here — but because every process loads the same
``.env`` into ``os.environ``, editing this one file configures both the new
agent and the pre-existing pipeline consistently.
"""

import os

from dotenv import load_dotenv

# No-op if no .env file is present (e.g. in CI or when variables are set
# directly in the shell).
load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")


def get_chat_model(temperature=0.0):
    """Return the shared Ollama chat model used by the ReAct agent.

    Imported lazily so that modules which only need the plain config
    constants above (for example a future script that just needs
    MONGODB_URI) do not require langchain-ollama to be installed.
    """
    from langchain_ollama import ChatOllama

    return ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_URL, temperature=temperature)
