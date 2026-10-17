"""Load the supplied DA&FW crop statistics workbook into MongoDB."""

import argparse
import sys
from pathlib import Path

from tools.excel_extractor.excel_extractory import (
    CropStatisticsExcelExtractor,
)


DEFAULT_FILE = (
    Path(__file__).resolve().parent
    / "data"
    / "Crop wise Area Production & Yield.xlsx"
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Normalize DA&FW crop statistics and store them in MongoDB."
    )
    parser.add_argument(
        "--file",
        default=str(DEFAULT_FILE),
        help="Path to the DA&FW Excel workbook.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and count records without writing to MongoDB.",
    )
    return parser.parse_args(argv)


def run_ingestion(workbook_path, dry_run=False, database=None):
    records = CropStatisticsExcelExtractor().load(workbook_path)
    years = sorted(
        {record["year"] for record in records},
        key=lambda value: int(value.split("-")[0]),
    )

    summary = {
        "records_processed": len(records),
        "crops": len({record["crop"] for record in records}),
        "first_year": years[0],
        "last_year": years[-1],
        "dry_run": dry_run,
    }

    if dry_run:
        return summary

    if database is None:
        from conn.crop_statistics_mongodb import CropStatisticsMongo
        database = CropStatisticsMongo()

    database.client.admin.command("ping")
    summary["count_before"] = database.collection.count_documents({})
    summary.update(database.upsert_records(records))
    summary["count_after"] = database.collection.count_documents({})
    return summary


def print_summary(summary):
    print("\nCrop statistics ingestion summary")
    print("---------------------------------")
    print(f"Records processed: {summary['records_processed']}")
    print(f"Crop groups: {summary['crops']}")
    print(f"Period: {summary['first_year']} to {summary['last_year']}")
    if summary["dry_run"]:
        print("Database write: skipped (--dry-run)")
        return
    print("MongoDB connection: OK")
    print(f"New records inserted: {summary['inserted']}")
    print(f"Existing records matched: {summary['matched']}")
    print(f"Existing records updated: {summary['modified']}")
    print(f"Database count before: {summary['count_before']}")
    print(f"Database count after: {summary['count_after']}")


def main(argv=None):
    try:
        args = parse_args(argv)
        summary = run_ingestion(args.file, dry_run=args.dry_run)
        print_summary(summary)
        return 0
    except Exception as exc:
        print(f"Crop statistics ingestion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
