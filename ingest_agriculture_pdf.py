"""Download, extract, and store an official Bihar agriculture PDF."""

import argparse
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from tools.pdf_extractor.agriculture_pdf_extractor import (
    AgriculturePDFExtractor,
)


DEFAULT_URL = (
    "https://betastate.bihar.gov.in/file_2/FileUpload/2024/Apr/"
    "18-Apr-2024/16/DyPage/f8cbff28-9f30-4b42-8557-75d10965d4b5.pdf"
)
DEFAULT_FILE = (
    Path(__file__).resolve().parent
    / "data"
    / "pdfs"
    / "bihar_annual_scheme_2022_23.pdf"
)
DEFAULT_TITLE = "Bihar Annual Scheme 2022-23 - Agriculture and Allied Sector"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Extract the agriculture chapter of an official Bihar PDF and "
            "store searchable page chunks in MongoDB."
        )
    )
    parser.add_argument("--file", default=str(DEFAULT_FILE))
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--start-page", type=int, default=11)
    parser.add_argument("--end-page", type=int, default=30)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def download_pdf(url, destination, *, refresh=False, timeout=180):
    destination = Path(destination)
    if destination.is_file() and not refresh:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = Request(
        url,
        headers={"User-Agent": "Bits-AI-Demo/1.0 PDF ingestion"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            with partial.open("wb") as output:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
        with partial.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ValueError("Downloaded content is not a PDF file")
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return destination


def run_ingestion(
    pdf_path,
    *,
    source_url,
    document_title,
    start_page,
    end_page,
    dry_run=False,
    database=None,
    extractor=None,
):
    extractor = extractor or AgriculturePDFExtractor()
    records = extractor.load(
        pdf_path,
        source_url=source_url,
        document_title=document_title,
        start_page=start_page,
        end_page=end_page,
    )
    summary = {
        "pages_requested": end_page - start_page + 1,
        "pages_extracted": len({record["page_number"] for record in records}),
        "chunks_processed": len(records),
        "characters_processed": sum(
            record["character_count"] for record in records
        ),
        "dry_run": dry_run,
        "source_url": source_url,
    }
    if dry_run:
        return summary

    if database is None:
        from conn.agriculture_documents_mongodb import (
            AgricultureDocumentsMongo,
        )

        database = AgricultureDocumentsMongo()

    database.client.admin.command("ping")
    summary["count_before"] = database.collection.count_documents({})
    summary.update(database.upsert_records(records))
    summary["count_after"] = database.collection.count_documents({})
    return summary


def print_summary(summary):
    print("\nAgriculture PDF ingestion summary")
    print("---------------------------------")
    print(f"Pages requested: {summary['pages_requested']}")
    print(f"Pages extracted: {summary['pages_extracted']}")
    print(f"Searchable chunks: {summary['chunks_processed']}")
    print(f"Characters extracted: {summary['characters_processed']}")
    print(f"Source: {summary['source_url']}")
    if summary["dry_run"]:
        print("Database write: skipped (--dry-run)")
        return
    print("MongoDB connection: OK")
    print(f"New chunks inserted: {summary['inserted']}")
    print(f"Existing chunks matched: {summary['matched']}")
    print(f"Existing chunks updated: {summary['modified']}")
    print(f"Database count before: {summary['count_before']}")
    print(f"Database count after: {summary['count_after']}")


def main(argv=None):
    try:
        args = parse_args(argv)
        pdf_path = download_pdf(
            args.url,
            args.file,
            refresh=args.refresh,
        )
        summary = run_ingestion(
            pdf_path,
            source_url=args.url,
            document_title=args.title,
            start_page=args.start_page,
            end_page=args.end_page,
            dry_run=args.dry_run,
        )
        print_summary(summary)
        return 0
    except Exception as exc:
        print(f"Agriculture PDF ingestion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
