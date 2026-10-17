"""Explicit source agents built on the project's verified extractors."""

import json
from pathlib import Path

from ingest_agriculture_sources import (
    DEFAULT_DOWNLOAD_DIRECTORY,
    DEFAULT_MANIFEST,
    extract_source,
    load_manifest,
    select_sources,
)
from ingest_crop_statistics import DEFAULT_FILE
from phase2.models import AgentResult, utc_now


def provenance(run_id, agent_id, source_type):
    return {
        "extraction_run_id": run_id,
        "extracting_agent": agent_id,
        "source_type": source_type,
        "extracted_at": utc_now(),
    }


class MandiSourceAgent:
    agent_id = "mandi_web_agent"
    source_id = "mandi"
    tool_name = "playwright_mandi_extractor"

    def __init__(self, urls, reader=None, database=None):
        self.urls = list(urls)
        self.reader = reader
        self.database = database

    def execute(self, run_id, *, dry_run=False):
        from tools.api_extractor.readMundiDatas import ReadMundiData

        reader = self.reader or ReadMundiData()
        started_at = utc_now()
        documents = reader.load_bihar_krishi_mandi_pages(self.urls)
        details = provenance(run_id, self.agent_id, "website")
        records_processed = sum(
            len(json.loads(document.page_content)) for document in documents
        )
        inserted = 0
        count_before = count_after = None
        if not dry_run:
            if self.database is None:
                from conn.mongodb import BiharCropMongo
                self.database = BiharCropMongo()
            self.database.client.admin.command("ping")
            count_before = self.database.collection.count_documents({})
            for document in documents:
                document.metadata.update(details)
                source_url = getattr(document, "source", None) or self.urls[0]
                inserted += self.database.write_mandi_records(
                    [document], source_url, provenance=details
                )
            count_after = self.database.collection.count_documents({})
        return AgentResult(
            agent_id=self.agent_id,
            source_id=self.source_id,
            tool_name=self.tool_name,
            tool_input={"urls": self.urls, "dry_run": dry_run},
            status="completed",
            summary={
                "sources_processed": len(self.urls),
                "records_processed": records_processed,
                "inserted": inserted,
                "count_before": count_before,
                "count_after": count_after,
                "dry_run": dry_run,
                "provenance": details,
            },
            started_at=started_at,
            completed_at=utc_now(),
        )


class CropStatisticsSourceAgent:
    agent_id = "crop_statistics_excel_agent"
    source_id = "crop_statistics"
    tool_name = "pandas_excel_extractor"

    def __init__(self, workbook_path=DEFAULT_FILE, extractor=None, database=None):
        self.workbook_path = Path(workbook_path)
        self.extractor = extractor
        self.database = database

    def execute(self, run_id, *, dry_run=False):
        from tools.excel_extractor.excel_extractory import CropStatisticsExcelExtractor

        extractor = self.extractor or CropStatisticsExcelExtractor()
        started_at = utc_now()
        records = extractor.load(self.workbook_path)
        details = provenance(run_id, self.agent_id, "excel")
        for record in records:
            record.update(details)
        write_result = {"inserted": 0, "matched": 0, "modified": 0}
        count_before = count_after = None
        if not dry_run:
            if self.database is None:
                from conn.crop_statistics_mongodb import CropStatisticsMongo
                self.database = CropStatisticsMongo()
            self.database.client.admin.command("ping")
            count_before = self.database.collection.count_documents({})
            write_result = self.database.upsert_records(records)
            count_after = self.database.collection.count_documents({})
        years = sorted(
            {record["year"] for record in records},
            key=lambda value: int(value.split("-")[0]),
        )
        return AgentResult(
            agent_id=self.agent_id,
            source_id=self.source_id,
            tool_name=self.tool_name,
            tool_input={"file": str(self.workbook_path), "dry_run": dry_run},
            status="completed",
            summary={
                "records_processed": len(records),
                "crop_groups": len({record["crop"] for record in records}),
                "period": {"first": years[0], "last": years[-1]},
                **write_result,
                "count_before": count_before,
                "count_after": count_after,
                "dry_run": dry_run,
                "provenance": details,
            },
            started_at=started_at,
            completed_at=utc_now(),
        )


class AgricultureDocumentsSourceAgent:
    agent_id = "multilingual_pdf_agent"
    source_id = "agriculture_documents"
    tool_name = "pypdf_tesseract_extractor"

    def __init__(
        self,
        manifest_path=DEFAULT_MANIFEST,
        source_ids=None,
        database=None,
        download_directory=DEFAULT_DOWNLOAD_DIRECTORY,
    ):
        self.manifest_path = Path(manifest_path)
        self.source_ids = source_ids
        self.database = database
        self.download_directory = Path(download_directory)

    def execute(self, run_id, *, dry_run=False):
        started_at = utc_now()
        selected = select_sources(
            load_manifest(self.manifest_path), self.source_ids
        )
        if not selected:
            raise ValueError("No enabled PDF source was selected")
        if not dry_run and self.database is None:
            from conn.agriculture_documents_mongodb import AgricultureDocumentsMongo
            self.database = AgricultureDocumentsMongo()
        count_before = (
            self.database.collection.count_documents({})
            if self.database is not None and not dry_run else None
        )
        totals = {
            "sources_processed": 0,
            "pages_requested": 0,
            "pages_extracted": 0,
            "direct_pages": 0,
            "ocr_pages": 0,
            "skipped_pages": 0,
            "chunks_processed": 0,
            "inserted": 0,
            "matched": 0,
            "modified": 0,
        }
        source_summaries = []
        details = provenance(run_id, self.agent_id, "pdf")
        for source in selected:
            records, report = extract_source(
                source,
                download_directory=self.download_directory,
            )
            for record in records:
                record.update(details)
            write_result = {"inserted": 0, "matched": 0, "modified": 0}
            if not dry_run:
                write_result = self.database.upsert_records(records)
            item = {
                "source_id": source["id"],
                "title": source["title"],
                "language": source["language"],
                "chunks_processed": len(records),
                **report,
                **write_result,
            }
            source_summaries.append(item)
            totals["sources_processed"] += 1
            for key in (
                "pages_requested", "pages_extracted", "direct_pages",
                "ocr_pages", "skipped_pages", "chunks_processed",
                "inserted", "matched", "modified",
            ):
                totals[key] += item[key]
        count_after = (
            self.database.collection.count_documents({})
            if self.database is not None and not dry_run else None
        )
        return AgentResult(
            agent_id=self.agent_id,
            source_id=self.source_id,
            tool_name=self.tool_name,
            tool_input={
                "manifest": str(self.manifest_path),
                "source_ids": [source["id"] for source in selected],
                "dry_run": dry_run,
            },
            status="completed",
            summary={
                **totals,
                "count_before": count_before,
                "count_after": count_after,
                "dry_run": dry_run,
                "sources": source_summaries,
                "provenance": details,
            },
            started_at=started_at,
            completed_at=utc_now(),
        )
