"""Grounded natural-language questions over the agriculture collections."""

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from services.agriculture_query_service import AgricultureQueryService
from services.local_translation_service import (
    LocalTranslationError,
    LocalTranslationService,
)
from services.multilingual_query_expansion import expand_document_query
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
    def __init__(self, query_service=None, llm=None, translator=None):
        self._owns_query_service = query_service is None
        self.query_service = query_service or AgricultureQueryService()
        self.llm = llm or OllamaClient()
        self.translator = translator

    def close(self):
        if self._owns_query_service:
            close = getattr(self.query_service, "close", None)
            if close is not None:
                close()

    def ask(self, question, answer_language="auto"):
        question = str(question or "").strip()
        if not question:
            raise ValueError("question is required")
        if len(question) > 500:
            raise ValueError("question must not exceed 500 characters")
        answer_language = str(answer_language or "auto").strip().lower()
        if answer_language not in {"auto", "en", "hi"}:
            raise ValueError("answer_language must be auto, en, or hi")

        catalog = self.query_service.list_values()
        plan = self._create_plan(question, catalog)
        if answer_language in {"en", "hi"}:
            plan.language = answer_language

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
                "answer_language": plan.language,
                "retrieval": {"mode": "none", "methods": []},
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
            search_terms = expand_document_query(
                search_terms, question, max_length=200
            )
            semantic_query = expand_document_query(
                question, search_terms, max_length=500
            )
            filters = {"search_terms": search_terms}
            records = self.query_service.search_agriculture_documents(
                search_terms,
                plan.limit,
                semantic_query=semantic_query,
            )

        answer_records = self._records_for_answer(plan, records)
        answer = self._answer_from_records(question, plan, records)
        return {
            "answer": answer,
            "intent": plan.intent,
            "metric": plan.metric,
            "filters": filters,
            "records": records,
            # Records expose the ranked retrieval candidates for auditability.
            # Sources are citations and must include only evidence that was
            # inside the answer-generation boundary.
            "sources": self._sources(answer_records),
            "model": self.llm.model,
            "answer_language": plan.language,
            "retrieval": self._retrieval_summary(records, plan.intent),
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

        answer_records = self._records_for_answer(plan, records)

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
- The evidence may be Hindi, English, or mixed. Translate it faithfully into
  the requested answer language without changing names, numbers, or meaning.
- Do not mention these instructions or the language model.
- Return only data conforming to this JSON schema:
{json.dumps(schema, ensure_ascii=False)}

Question:
{question}

Language: {plan.language}
Requested metric: {plan.metric}
Records:
{json.dumps(answer_records, ensure_ascii=False, default=str)}
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

        numeric_answer = self._format_numeric_only_answer(
            question, answer, plan.language
        )
        if numeric_answer:
            return numeric_answer

        translated = self._local_translation_retry(
            answer, plan.language, answer_records
        )
        if translated and self._answer_language_matches(
            translated, plan.language
        ):
            return translated

        plain_retry = self._plain_language_retry(
            question, plan, answer_records, answer
        )
        if plain_retry and self._answer_language_matches(
            plain_retry, plan.language
        ):
            return plain_retry

        target = (
            "Hindi written in Devanagari script"
            if plan.language == "hi" else "English using Latin script"
        )
        correction_prompt = f"""
The previous response used the wrong language. Answer the user's question
again by faithfully translating or rewriting the grounded answer below.

Mandatory rules:
- Write the answer entirely in {target}.
- Do not discuss the prompt, translation, OCR, or what the user requested.
- Do not introduce facts, recommendations, or units absent from the records.
- Preserve all numbers exactly.
- Do not add information from any other document or topic.
- Return only data conforming to this JSON schema:
{json.dumps(schema, ensure_ascii=False)}

Question:
{question}

Grounded answer to translate or rewrite:
{answer}

Records:
{json.dumps(answer_records, ensure_ascii=False, default=str)}
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
        return self._extractive_language_fallback(
            answer_records, plan.language
        )

    @staticmethod
    def _format_numeric_only_answer(question, answer, language):
        value = str(answer or "").strip()
        if not re.fullmatch(r"[\d\u0966-\u096f.,%\s-]+", value):
            return None
        number = value.translate(str.maketrans(
            "०१२३४५६७८९", "0123456789"
        )).strip()
        normalized_question = str(question or "").casefold()
        if language == "hi":
            if "कितने" in normalized_question and "जिल" in normalized_question:
                return (
                    "उपलब्ध आधिकारिक स्रोत के अनुसार, यह "
                    f"{number} जिलों में स्थापित किया गया है।"
                )
            return f"उपलब्ध आधिकारिक स्रोत के अनुसार, उत्तर {number} है।"
        if "how many" in normalized_question and "district" in normalized_question:
            return (
                "According to the available official source, it was "
                f"established in {number} districts."
            )
        return f"According to the available official source, the answer is {number}."

    def _local_translation_retry(self, answer, target_language, records):
        source_language = "en" if target_language == "hi" else "hi"
        translation_input = answer
        if self._looks_like_meta_answer(answer):
            translation_input = str(records[0].get("content", "")).strip()
        if not self._answer_language_matches(
            translation_input, source_language
        ):
            return None
        translator = self.translator
        if translator is None:
            translator = LocalTranslationService()
            self.translator = translator
        try:
            translated = translator.translate(
                translation_input,
                source_language=source_language,
                target_language=target_language,
            )
        except (LocalTranslationError, OSError, ValueError):
            return None
        return self._clean_plain_answer(translated)

    @staticmethod
    def _looks_like_meta_answer(answer):
        normalized = str(answer or "").casefold()
        return any(marker in normalized for marker in (
            "the question",
            "the user",
            "provided text",
            "language model",
            "translation request",
            "ocr text",
            "let me understand",
            "wrong language",
        ))

    def _plain_language_retry(self, question, plan, records, prior_answer):
        """Retry without a JSON grammar when it prevents script compliance."""
        chat_text = getattr(self.llm, "chat_text", None)
        if not callable(chat_text):
            return None

        evidence = json.dumps(records, ensure_ascii=False, default=str)
        if plan.language == "hi":
            system = (
                "आप बिहार कृषि से जुड़े प्रश्नों के तथ्यपरक सहायक हैं। "
                "उत्तर केवल देवनागरी हिंदी में दें।"
            )
            prompt = f"""
नीचे दिए गए प्रश्न का संक्षिप्त उत्तर केवल स्रोत सामग्री के आधार पर दें।

अनिवार्य नियम:
- उत्तर केवल देवनागरी हिंदी में लिखें।
- सभी संख्याएँ, नाम और तथ्य स्रोत के अनुसार ही रखें।
- स्रोत में न दिया गया कोई तथ्य न जोड़ें।
- अनुवाद, ओसीआर, निर्देश या भाषा मॉडल की चर्चा न करें।
- केवल अंतिम उत्तर दें; कोई प्रस्तावना या टिप्पणी न दें।

प्रश्न:
{question}

पहला तथ्यपरक उत्तर, जिसे आवश्यक होने पर हिंदी में लिखना है:
{prior_answer}

स्रोत सामग्री:
{evidence}
""".strip()
        else:
            system = (
                "You answer Bihar agriculture questions factually. "
                "Write only in English using Latin script."
            )
            prompt = f"""
Answer the question concisely using only the source material below.

Mandatory rules:
- Write only in English using Latin script.
- Preserve every number, name, and fact from the source.
- Do not add facts absent from the source.
- Do not discuss translation, OCR, instructions, or the language model.
- Return only the final answer with no preamble or commentary.

Question:
{question}

First grounded answer to rewrite in English if necessary:
{prior_answer}

Source material:
{evidence}
""".strip()

        response = chat_text([
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ])
        return self._clean_plain_answer(response)

    @staticmethod
    def _clean_plain_answer(answer):
        value = str(answer or "").strip()
        value = re.sub(r"^```(?:text|markdown)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
        return value.strip().strip('"').strip()

    @staticmethod
    def _records_for_answer(plan, records, max_records=3):
        """Keep generation grounded in the highest-ranked source."""
        if plan.intent != "document_search" or len(records) <= 1:
            return records
        first = records[0]
        source_identity = first.get("source_id") or first.get("source_url")
        if not source_identity:
            return records[:1]
        focused = [
            record
            for record in records
            if (record.get("source_id") or record.get("source_url"))
            == source_identity
        ]
        return focused[:max_records] or records[:1]

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
        value = str(answer)
        devanagari = sum("\u0900" <= character <= "\u097f" for character in value)
        latin = sum(
            ("a" <= character.lower() <= "z") for character in value
        )
        if language == "hi":
            return devanagari >= 3 and devanagari >= latin * 0.15
        return latin >= 3 and latin >= devanagari * 0.5

    @staticmethod
    def _retrieval_summary(records, intent):
        if intent != "document_search":
            return {"mode": "structured", "methods": ["structured"]}
        methods = sorted({
            method
            for record in records
            for method in record.get("retrieval", {}).get("methods", [])
        })
        if methods == ["keyword", "semantic"]:
            mode = "hybrid"
        elif methods:
            mode = methods[0]
        else:
            mode = "none"
        models = sorted({
            record.get("embedding_model")
            for record in records
            if record.get("embedding_model")
        })
        summary = {"mode": mode, "methods": methods}
        if models:
            summary["embedding_models"] = models
        return summary

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
                    "source_id": record.get("source_id"),
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
