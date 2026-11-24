"""PDF/API ingestion helpers used by the main application."""

import hashlib
from pathlib import Path

from conn.api_documents_mongodb import ApiDocumentsMongo
from tools.api_extractor.generic_api import BoundedApiReader


def translate_hindi_chunks(records, translator_factory=None):
    """Translate Hindi PDF chunks while retaining their original text."""
    hindi_records = [
        record for record in records if record.get("language") == "hi"
    ]
    if not hindi_records:
        return records

    if translator_factory is None:
        from tools.translateEngToHindi.translate import Translator

        translator_factory = Translator
    translator = translator_factory()

    translated_records = []
    for record in records:
        translated_record = dict(record)
        if translated_record.get("language") == "hi":
            original = translated_record["content"]
            translated = translator.translate(original)
            if not isinstance(translated, str) or not translated.strip():
                raise RuntimeError(
                    "Hindi translation returned empty content for "
                    f"page {record.get('page_number')}, "
                    f"chunk {record.get('chunk_index')}"
                )
            translated_record["translated_content"] = translated.strip()
            translated_record["translation_language"] = "en"
            translated_record["translation_model"] = getattr(translator, "model_name", "custom")
            translated_record["translation_status"] = "machine_translation_unverified"
        translated_records.append(translated_record)
    return translated_records


def ingest_pdf(
    pdf_path,
    *,
    database=None,
    translator_factory=None,
    force_ocr=False,
    ocr_enabled=True,
    translate=False,
    write=False,
):
    from tools.pdf_extractor.agriculture_pdf_extractor import (
        AgriculturePDFExtractor,
    )

    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found: {path}")
    if force_ocr and not ocr_enabled:
        raise ValueError("Forced OCR cannot be used when OCR is disabled")

    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    extractor = AgriculturePDFExtractor(ocr_enabled=ocr_enabled)
    records = extractor.load(
        path,
        source_url=path.as_uri(),
        document_title=path.stem,
        force_ocr=force_ocr,
    )
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != digest:
            raise ValueError("PDF bytes changed during extraction; no data was saved")
    for record in records:
        record["source_hash"] = digest
    if translate or translator_factory is not None:
        records = translate_hindi_chunks(records, translator_factory=translator_factory)
    report = {
        "source": str(path), "source_sha256": digest,
        "detected_languages": extractor.last_report["language_counts"],
        "chunks_processed": len(records), "saved": write,
    }
    if not records:
        raise ValueError("No source text was extracted; review the PDF/OCR configuration")
    if not write:
        return {**report, "sample_chunks": records[:3]}

    owns_database = database is None
    if database is None:
        from conn.agriculture_documents_mongodb import (
            AgricultureDocumentsMongo,
        )

        database = AgricultureDocumentsMongo()

    try:
        database.client.admin.command("ping")
        count_before = database.collection.count_documents({})
        write_result = database.upsert_records(records)
        count_after = database.collection.count_documents({})
    finally:
        if owns_database:
            database.client.close()

    return {
        **report,
        "count_before": count_before,
        "count_after": count_after,
        **write_result,
    }


def ingest_api_urls(
    urls,
    *,
    database=None,
    reader=None,
    allowed_hosts=(),
    write=False,
):
    if not urls:
        return {
            "sources_processed": 0,
            "records_processed": 0,
            "inserted": 0,
            "matched": 0,
            "modified": 0,
        }
    if reader is None:
        reader = BoundedApiReader(allowed_hosts=allowed_hosts)
    responses = reader.load(urls)
    if not write:
        return {
            "saved": False, "sources_processed": len(responses),
            "records_processed": sum(len(response["records"]) for response in responses),
            "sources": [
                {
                    "source_url": response["source_url"],
                    "source_sha256": response.get("source_sha256"),
                    "response_kind": response["response_kind"],
                    "record_count": len(response["records"]),
                    "sample": [
                        {"record": record, "locator": locator}
                        for record, locator in zip(
                            response["records"][:5], response.get("locators", [])[:5],
                        )
                    ],
                } for response in responses
            ],
        }
    owns_database = database is None
    if database is None:
        database = ApiDocumentsMongo()

    try:
        database.client.admin.command("ping")
        count_before = database.collection.count_documents({})
        totals = {"inserted": 0, "matched": 0, "modified": 0}
        records_processed = 0
        for response in responses:
            records = response["records"]
            write_result = database.upsert_records(
                response["source_url"],
                response["response_kind"],
                records,
                source_sha256=response.get("source_sha256"),
                locators=response.get("locators"),
            )
            records_processed += len(records)
            for key in totals:
                totals[key] += write_result[key]
        count_after = database.collection.count_documents({})
    finally:
        if owns_database:
            database.close()

    return {
        "saved": True, "sources_processed": len(responses),
        "records_processed": records_processed,
        "count_before": count_before,
        "count_after": count_after,
        **totals,
    }
