"""Grounded natural-language questions over the agriculture collections."""

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from services.agriculture_query_service import AgricultureQueryService
from services.ollama_client import OllamaClient


class QueryPlan(BaseModel):
    intent: Literal[
        "mandi_price",
        "crop_statistics",
        "document_search",
        "unsupported",
    ]
    crop: str | None = None
    district: str | None = None
    market: str | None = None
    variety: str | None = None
    season: str | None = None
    year: str | None = None
    date: str | None = None
    search_terms: str | None = Field(default=None, max_length=200)
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
        self._owns_query_service = query_service is None
        self.query_service = query_service or AgricultureQueryService()
        self.llm = llm or OllamaClient()

    def close(self):
        if self._owns_query_service:
            close = getattr(self.query_service, "close", None)
            if close is not None:
                close()

    def ask(self, question):
        question = str(question or "").strip()
        if not question:
            raise ValueError("question is required")
        if len(question) > 500:
            raise ValueError("question must not exceed 500 characters")

        catalog = self.query_service.list_values()
        plan = self._create_plan(question, catalog)

        if plan.intent == "unsupported":
            if plan.language == "hi":
                answer = (
                    "मैं उपलब्ध मंडी भाव, ऐतिहासिक फसल क्षेत्रफल, उत्पादन "
                    "और उपज के आँकड़ों तथा सूचीबद्ध आधिकारिक कृषि दस्तावेजों "
                    "की सामग्री से जुड़े प्रश्नों का उत्तर दे सकता हूँ।"
                )
            else:
                answer = (
                    "I can answer questions about the available mandi prices "
                    "and historical crop area, production, and yield data, "
                    "as well as material in the indexed official agriculture "
                    "documents."
                )
            return {
                "answer": answer,
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
        elif plan.intent == "crop_statistics":
            records = self.query_service.find_crop_statistics(
                filters, plan.limit
            )
        else:
            search_terms = str(plan.search_terms or question).strip()
            filters = {"search_terms": search_terms}
            records = self.query_service.search_agriculture_documents(
                search_terms, plan.limit
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
- Use document_search for questions about government agriculture schemes,
  policies, programmes, objectives, seeds, mechanization, organic farming,
  horticulture, irrigation, soil conservation, livestock, fisheries, or other
  narrative material in the official report.
- If the question explicitly refers to a report, handbook, brochure, policy,
  scheme, पुस्तिका, रिपोर्ट, or योजना, always use document_search even when
  words such as production or yield also appear.
- For document_search, provide concise search_terms containing the important
  nouns from the question. Preserve important Devanagari nouns for a Hindi
  question. Hindi search terms may also include a useful English equivalent.
- Use unsupported for advice, weather forecasts, or topics not answerable from
  the available prices, statistics, or official agriculture report.
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
            if plan.language == "hi":
                return (
                    "इस प्रश्न के लिए उपलब्ध कृषि डेटा स्रोतों में कोई "
                    "मिलता-जुलता रिकॉर्ड नहीं मिला।"
                )
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
- State the date, financial year, or source page when it is relevant and
  present in the records.
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
        answer = GroundedAnswer.model_validate(response).answer
        if self._answer_language_matches(answer, plan.language):
            return answer

        target = (
            "Hindi written in Devanagari script"
            if plan.language == "hi" else "English using Latin script"
        )
        correction_prompt = f"""
The previous response used the wrong language. Answer the user's question
again using only the supplied records.

Mandatory rules:
- Write the answer entirely in {target}.
- Do not discuss the prompt, translation, OCR, or what the user requested.
- Do not introduce facts, recommendations, or units absent from the records.
- Preserve all numbers exactly.
- Return only data conforming to this JSON schema:
{json.dumps(schema, ensure_ascii=False)}

Question:
{question}

Records:
{json.dumps(records, ensure_ascii=False, default=str)}
""".strip()
        corrected_response = self.llm.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a grounded bilingual agriculture assistant. "
                        "The requested output language is mandatory."
                    ),
                },
                {"role": "user", "content": correction_prompt},
            ],
            schema,
        )
        corrected = GroundedAnswer.model_validate(
            corrected_response
        ).answer
        if self._answer_language_matches(corrected, plan.language):
            return corrected
        return self._extractive_language_fallback(records, plan.language)

    @classmethod
    def _extractive_language_fallback(
        cls, records, language, max_characters=800
    ):
        snippets = []
        used_characters = 0
        for record in records:
            content = re.sub(
                r"\s+", " ", str(record.get("content", ""))
            ).strip()
            for sentence in re.split(r"(?<=[.!?\u0964])\s+", content):
                sentence = sentence.strip()
                if (
                    len(sentence) < 20
                    or not cls._answer_language_matches(sentence, language)
                ):
                    continue
                remaining = max_characters - used_characters
                if remaining <= 0:
                    break
                if len(sentence) > remaining:
                    sentence = sentence[:remaining].rstrip()
                snippets.append(sentence)
                used_characters += len(sentence) + 1
                if used_characters >= max_characters:
                    break
            if used_characters >= max_characters:
                break
        if not snippets:
            raise ValueError(
                "No retrieved source text matched the requested answer language"
            )
        prefix = (
            "\u0909\u092a\u0932\u092c\u094d\u0927 \u0938\u094d\u0930\u094b\u0924\u094b\u0902 "
            "\u0915\u0947 \u0905\u0928\u0941\u0938\u093e\u0930: "
            if language == "hi" else "According to the available sources: "
        )
        return prefix + " ".join(snippets)

    @staticmethod
    def _answer_language_matches(answer, language):
        has_devanagari = any(
            "\u0900" <= character <= "\u097f"
            for character in str(answer)
        )
        return has_devanagari if language == "hi" else not has_devanagari

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
        elif plan.intent == "crop_statistics":
            values = {
                "crop": plan.crop,
                "season": plan.season,
                "year": plan.year,
            }
            allowed = {
                "crop": catalog.get("statistical_crops", []),
                "season": catalog.get("seasons", []),
            }
        else:
            return {}

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
            page_number = record.get("page_number")
            document_title = record.get("document_title")
            source_organization = record.get("source_organization")
            language = record.get("language")
            item = {
                key: value
                for key, value in {
                    "source": source,
                    "source_file": source_file,
                    "document_title": document_title,
                    "page_number": page_number,
                    "organization": source_organization,
                    "language": language,
                }.items()
                if value is not None
            }
            identity = tuple(sorted(item.items()))
            if item and identity not in seen:
                seen.add(identity)
                sources.append(item)
        return sources
