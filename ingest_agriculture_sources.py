"""Ingest an allowlisted collection of multilingual agriculture PDFs."""

import argparse
import sys
from pathlib import Path

import yaml

from ingest_agriculture_pdf import download_pdf
from tools.pdf_extractor.agriculture_pdf_extractor import (
    AgriculturePDFExtractor,
)


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = PROJECT_ROOT / "sources" / "agriculture_sources.yaml"
DEFAULT_DOWNLOAD_DIRECTORY = PROJECT_ROOT / "data" / "pdfs"
REQUIRED_SOURCE_FIELDS = {
    "id",
    "title",
    "organization",
    "language",
    "url",
    "filename",
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Download and ingest allowlisted English and Hindi agriculture "
            "PDFs with optional OCR fallback."
        )
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument(
        "--source",
        action="append",
        dest="source_ids",
        help="Source id to ingest. Repeat to select multiple sources.",
    )
    parser.add_argument("--list-sources", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--force-ocr", action="store_true")
    parser.add_argument("--no-ocr", action="store_true")
    return parser.parse_args(argv)


def load_manifest(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Source manifest not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Source manifest must contain a non-empty sources list")

    resolved = []
    seen_ids = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"Source {index + 1} must be a mapping")
        missing = REQUIRED_SOURCE_FIELDS - source.keys()
        if missing:
            raise ValueError(
                f"Source {index + 1} is missing: "
                + ", ".join(sorted(missing))
            )
        source_id = str(source["id"]).strip()
        if not source_id or source_id in seen_ids:
            raise ValueError(f"Source id must be non-empty and unique: {source_id}")
        seen_ids.add(source_id)

        filename = Path(str(source["filename"])).name
        if filename != str(source["filename"]) or not filename.lower().endswith(".pdf"):
            raise ValueError(f"Source {source_id} has an unsafe PDF filename")

        start_page = int(source.get("start_page", 1))
        end_page = source.get("end_page")
        end_page = int(end_page) if end_page is not None else None
        if start_page < 1 or (end_page is not None and end_page < start_page):
            raise ValueError(f"Source {source_id} has an invalid page range")

        resolved.append({
            **source,
            "id": source_id,
            "filename": filename,
            "start_page": start_page,
            "end_page": end_page,
            "enabled": bool(source.get("enabled", True)),
        })
    return resolved


def select_sources(sources, source_ids=None):
    if not source_ids:
        return [source for source in sources if source["enabled"]]
    requested = set(source_ids)
    selected = [source for source in sources if source["id"] in requested]
    missing = requested - {source["id"] for source in selected}
    if missing:
        raise ValueError("Unknown source id(s): " + ", ".join(sorted(missing)))
    return selected


def extract_source(
    source,
    *,
    download_directory=DEFAULT_DOWNLOAD_DIRECTORY,
    refresh=False,
    force_ocr=False,
    ocr_enabled=True,
):
    destination = Path(download_directory) / source["filename"]
    pdf_path = download_pdf(
        source["url"],
        destination,
        refresh=refresh,
    )
    extractor = AgriculturePDFExtractor(ocr_enabled=ocr_enabled)
    records = extractor.load(
        pdf_path,
        source_url=source["url"],
        document_title=source["title"],
        start_page=source["start_page"],
        end_page=source["end_page"],
        declared_language=source["language"],
        force_ocr=force_ocr or bool(source.get("force_ocr", False)),
    )
    for record in records:
        record.update({
            "source_id": source["id"],
            "source_organization": source["organization"],
            "declared_language": source["language"],
        })
    return records, extractor.last_report


def run_ingestion(
    sources,
    *,
    dry_run=False,
    refresh=False,
    force_ocr=False,
    ocr_enabled=True,
    database=None,
    download_directory=DEFAULT_DOWNLOAD_DIRECTORY,
):
    if database is None and not dry_run:
        from conn.agriculture_documents_mongodb import (
            AgricultureDocumentsMongo,
        )

        database = AgricultureDocumentsMongo()
        database.client.admin.command("ping")

    count_before = (
        database.collection.count_documents({}) if database is not None else None
    )
    source_summaries = []
    totals = {
        "sources_processed": 0,
        "pages_requested": 0,
        "pages_extracted": 0,
        "direct_pages": 0,
        "ocr_pages": 0,
        "skipped_pages": 0,
        "chunks_processed": 0,
        "characters_processed": 0,
        "inserted": 0,
        "matched": 0,
        "modified": 0,
    }

    for source in sources:
        records, report = extract_source(
            source,
            download_directory=download_directory,
            refresh=refresh,
            force_ocr=force_ocr,
            ocr_enabled=ocr_enabled,
        )
        write_result = {"inserted": 0, "matched": 0, "modified": 0}
        if database is not None:
            write_result = database.upsert_records(records)

        summary = {
            "id": source["id"],
            "title": source["title"],
            "language": source["language"],
            "chunks_processed": len(records),
            "characters_processed": sum(
                record["character_count"] for record in records
            ),
            **report,
            **write_result,
        }
        source_summaries.append(summary)
        totals["sources_processed"] += 1
        for key in (
            "pages_requested",
            "pages_extracted",
            "direct_pages",
            "ocr_pages",
            "skipped_pages",
            "chunks_processed",
            "characters_processed",
            "inserted",
            "matched",
            "modified",
        ):
            totals[key] += summary[key]

    totals["dry_run"] = dry_run
    totals["sources"] = source_summaries
    totals["count_before"] = count_before
    totals["count_after"] = (
        database.collection.count_documents({}) if database is not None else None
    )
    return totals


def print_sources(sources):
    print("\nConfigured agriculture sources")
    print("------------------------------")
    for source in sources:
        status = "enabled" if source["enabled"] else "disabled"
        page_range = str(source["start_page"])
        if source["end_page"] is not None:
            page_range += f"-{source['end_page']}"
        else:
            page_range += "-end"
        print(
            f"{source['id']}: {source['language']}, pages {page_range}, "
            f"{status}\n  {source['title']}\n  {source['url']}"
        )


def print_summary(summary):
    for source in summary["sources"]:
        print(f"\nSource: {source['id']}")
        print(f"  Title: {source['title']}")
        print(f"  Declared language: {source['language']}")
        print(f"  Pages extracted: {source['pages_extracted']}/{source['pages_requested']}")
        print(f"  Direct/OCR/skipped pages: {source['direct_pages']}/{source['ocr_pages']}/{source['skipped_pages']}")
        print(f"  Detected languages: {source['language_counts']}")
        print(f"  Searchable chunks: {source['chunks_processed']}")

    print("\nMultilingual source ingestion summary")
    print("-------------------------------------")
    print(f"Sources processed: {summary['sources_processed']}")
    print(f"Pages extracted: {summary['pages_extracted']}/{summary['pages_requested']}")
    print(f"Direct text pages: {summary['direct_pages']}")
    print(f"OCR pages: {summary['ocr_pages']}")
    print(f"Skipped pages: {summary['skipped_pages']}")
    print(f"Searchable chunks: {summary['chunks_processed']}")
    print(f"Characters extracted: {summary['characters_processed']}")
    if summary["dry_run"]:
        print("Database write: skipped (--dry-run)")
    else:
        print("MongoDB connection: OK")
        print(f"New chunks inserted: {summary['inserted']}")
        print(f"Existing chunks matched: {summary['matched']}")
        print(f"Existing chunks updated: {summary['modified']}")
        print(f"Database count before: {summary['count_before']}")
        print(f"Database count after: {summary['count_after']}")


def main(argv=None):
    try:
        args = parse_args(argv)
        sources = load_manifest(args.manifest)
        if args.list_sources:
            print_sources(sources)
            return 0
        selected = select_sources(sources, args.source_ids)
        if not selected:
            raise ValueError("No enabled sources were selected")
        summary = run_ingestion(
            selected,
            dry_run=args.dry_run,
            refresh=args.refresh,
            force_ocr=args.force_ocr,
            ocr_enabled=not args.no_ocr,
        )
        print_summary(summary)
        return 0
    except Exception as exc:
        print(f"Multilingual source ingestion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
