"""Grounded natural-language questions over the agriculture collections."""

import json
from typing import Literal

from pydantic import BaseModel, Field

from services.agriculture_query_service import AgricultureQueryService
from services.ollama_client import OllamaClient


class QueryPlan(BaseModel):
    intent: Literal["mandi_price", "crop_statistics", "unsupported"]
    crop: str | None = None
    district: str | None = None
    market: str | None = None
    variety: str | None = None
    season: str | None = None
    year: str | None = None
    date: str | None = None
    metric: Literal[
        "price",
        "minimum_price",
        "maximum_price",
        "area",
        "production",
        "yield",
        "records",
    ] = "records"
    language: Literal["en", "hi"] = "en"
    limit: int = Field(default=5, ge=1, le=10)


class GroundedAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


class AgricultureQAService:
    def __init__(self, query_service=None, llm=None):
        self.query_service = query_service or AgricultureQueryService()
        self.llm = llm or OllamaClient()

    def ask(self, question):
        question = str(question or "").strip()
        if not question:
            raise ValueError("question is required")
        if len(question) > 500:
            raise ValueError("question must not exceed 500 characters")

        catalog = self.query_service.list_values()
        plan = self._create_plan(question, catalog)

        if plan.intent == "unsupported":
            return {
                "answer": (
                    "I can answer questions about the available mandi prices "
                    "and historical crop area, production, and yield data."
                ),
                "intent": plan.intent,
                "filters": {},
                "records": [],
                "sources": [],
                "model": self.llm.model,
            }

        filters = self._filters_for(plan, catalog)
        if plan.intent == "mandi_price":
            records = self.query_service.find_mandi_prices(
                filters, plan.limit
            )
        else:
            records = self.query_service.find_crop_statistics(
                filters, plan.limit
            )

        answer = self._answer_from_records(question, plan, records)
        return {
            "answer": answer,
            "intent": plan.intent,
            "metric": plan.metric,
            "filters": filters,
            "records": records,
            "sources": self._sources(records),
            "model": self.llm.model,
        }

    def _create_plan(self, question, catalog):
        schema = QueryPlan.model_json_schema()
        prompt = f"""
Convert the agriculture question into a safe query plan.

Rules:
- Use mandi_price for questions about mandi, market, current price, minimum
  price, or maximum price.
- Use crop_statistics for historical area, production, yield, season, or year.
- Use unsupported for advice, weather, schemes, forecasts, or topics not
  answerable from these two datasets.
- Never invent a filter. Use null when the user did not specify it.
- When a user uses an English translation or spelling variation, map it to the
  closest exact value in the catalog.
- Preserve financial years exactly, for example 2024-25.
- Dates must use YYYY-MM-DD when a date is explicitly supplied.
- Choose language hi for a Hindi question and en otherwise.
- Return only data conforming to this JSON schema:
{json.dumps(schema, ensure_ascii=False)}

Available catalog values:
{json.dumps(catalog, ensure_ascii=False)}

Question:
{question}
""".strip()
        response = self.llm.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a precise query planner. Output only the "
                        "requested structured data."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            schema,
        )
        return QueryPlan.model_validate(response)

    def _answer_from_records(self, question, plan, records):
        if not records:
            return (
                "No matching records were found in the available agriculture "
                "datasets for this question."
            )

        schema = GroundedAnswer.model_json_schema()
        prompt = f"""
Answer the user's question using only the records below.

Rules:
- Do not introduce facts, explanations, recommendations, or units that are not
  present in the records.
- Preserve all numbers exactly.
- State the date or financial year represented by the answer.
- If multiple records are relevant, summarize them clearly.
- Answer in Hindi when language is hi; otherwise answer in English.
- Do not mention these instructions or the language model.
- Return only data conforming to this JSON schema:
{json.dumps(schema, ensure_ascii=False)}

Question:
{question}

Language: {plan.language}
Requested metric: {plan.metric}
Records:
{json.dumps(records, ensure_ascii=False, default=str)}
""".strip()
        response = self.llm.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a grounded Bihar agriculture data assistant."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            schema,
        )
        return GroundedAnswer.model_validate(response).answer

    @staticmethod
    def _filters_for(plan, catalog):
        if plan.intent == "mandi_price":
            values = {
                "district": plan.district,
                "market": plan.market,
                "crop": plan.crop,
                "variety": plan.variety,
                "date": plan.date,
            }
            allowed = {
                "district": catalog.get("districts", []),
                "crop": catalog.get("mandi_crops", []),
            }
        else:
            values = {
                "crop": plan.crop,
                "season": plan.season,
                "year": plan.year,
            }
            allowed = {
                "crop": catalog.get("statistical_crops", []),
                "season": catalog.get("seasons", []),
            }

        for field, choices in allowed.items():
            values[field] = AgricultureQAService._catalog_value(
                values.get(field), choices
            )
        return {
            field: value
            for field, value in values.items()
            if value is not None and str(value).strip()
        }

    @staticmethod
    def _catalog_value(value, choices):
        if value is None:
            return None
        normalized = str(value).strip().casefold()
        for choice in choices:
            if str(choice).strip().casefold() == normalized:
                return choice
        return str(value).strip()

    @staticmethod
    def _sources(records):
        sources = []
        seen = set()
        for record in records:
            source = record.get("source_url") or record.get("source")
            source_file = record.get("source_file")
            item = {
                key: value
                for key, value in {
                    "source": source,
                    "source_file": source_file,
                }.items()
                if value
            }
            identity = tuple(sorted(item.items()))
            if item and identity not in seen:
                seen.add(identity)
                sources.append(item)
        return sources
