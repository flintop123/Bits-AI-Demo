# Grounded QA Agent

## Responsibility

The agent converts an English or Hindi agriculture question into an allowlisted query plan, retrieves records from MongoDB, and generates an answer using only the retrieved evidence.

## Inputs and outputs

| Item | Contract |
|---|---|
| Input | One natural-language question and optional answer language |
| Decisions | Intent, allowlisted filters, metric, language and result limit |
| Tools | MongoDB queries, hybrid document retrieval, Qwen3 through Ollama |
| Output | Answer, plan, filters, retrieved records and source citations |
| Storage | Read-only for agriculture content collections |

## Model and fixed-code boundary

Qwen3 chooses a structured query plan inside a Pydantic schema and verbalizes retrieved evidence. Fixed code validates the plan, restricts fields and limits, executes MongoDB queries, computes market statistics, constrains answer evidence, checks answer language and rejects unsupported requests. BGE-M3 creates retrieval embeddings but does not generate answers.

## Tools and models

- `qwen3:4b` for query planning and grounded answer wording
- `bge-m3` for multilingual semantic retrieval
- MongoDB keyword/text and vector retrieval
- Pydantic validation

## Error case

If the model uses the wrong answer language, the service retries within the same evidence boundary and then uses a deterministic extractive fallback. Ollama failure is returned as a service error; the system does not fabricate an answer.

## Limitations

- Answers are limited to records already collected and indexed.
- Local-model wording quality can vary, so numeric fidelity, citations and language are checked independently.
- The system provides descriptive market statistics, not price forecasts or trading recommendations.
