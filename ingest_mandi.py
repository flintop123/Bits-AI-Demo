"""Command-line entry point for ingesting Bihar mandi prices into MongoDB."""

import argparse
import json
import sys


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Collect Bihar mandi prices and store them in MongoDB."
    )
    parser.add_argument(
        "--url",
        dest="urls",
        action="append",
        help="Mandi URL to collect. May be supplied more than once.",
    )
    return parser.parse_args(argv)


def resolve_urls(cli_urls, config):
    urls = cli_urls or config.get("bihar_krishi", {}).get("urls", [])
    if not urls:
        raise ValueError(
            "No mandi URL was provided through --url or config.yaml"
        )
    return urls


def count_records(documents):
    total = 0
    for document in documents:
        records = json.loads(document.page_content)
        if not isinstance(records, list):
            raise ValueError("Mandi document content must be a JSON list")
        total += len(records)
    return total


def run_ingestion(urls, database=None, reader=None):
    if database is None:
        from conn.mongodb import BiharCropMongo
        database = BiharCropMongo()

    if reader is None:
        from tools.api_extractor.readMundiDatas import ReadMundiData
        reader = ReadMundiData()

    database.client.admin.command("ping")
    count_before = database.collection.count_documents({})
    documents = reader.load_bihar_krishi_mandi_pages(urls)

    processed = count_records(documents)
    inserted = 0

    for document in documents:
        source_url = (
            getattr(document, "source", None)
            or document.metadata.get("source")
            or urls[0]
        )
        inserted += database.write_mandi_records(
            [document],
            source_url=source_url,
        )

    count_after = database.collection.count_documents({})

    return {
        "sources": len(urls),
        "processed": processed,
        "inserted": inserted,
        "count_before": count_before,
        "count_after": count_after,
    }


def print_summary(summary):
    print("\nIngestion summary")
    print("-----------------")
    print("MongoDB connection: OK")
    print(f"Sources processed: {summary['sources']}")
    print(f"Records processed: {summary['processed']}")
    print(f"New records inserted: {summary['inserted']}")
    print(f"Database count before: {summary['count_before']}")
    print(f"Database count after: {summary['count_after']}")


def main(argv=None):
    try:
        from config_reader import read_config

        args = parse_args(argv)
        urls = resolve_urls(args.urls, read_config())
        print_summary(run_ingestion(urls))
        return 0
    except Exception as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
