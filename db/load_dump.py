"""Validate the JSONL dump and load its relational mirror into SQLite."""

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTIONS = (
    "mandi_prices", "crop_statistics", "agriculture_documents",
    "mandi_locations",
)
REQUIRED = {
    "mandi_prices": {"source_record_id", "district", "market", "date", "crop", "source_url"},
    "crop_statistics": {"crop", "season", "year", "source_file", "source_row"},
    "agriculture_documents": {"content_hash", "content", "page_number", "source_url"},
    "mandi_locations": {"market_code", "market_name", "district_name", "location", "verification_status"},
}


def read_collection(folder, name):
    path = folder / f"{name}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"Required dump file is missing: {path}")
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        missing = REQUIRED[name] - record.keys()
        if missing:
            raise ValueError(f"{path}:{line_number} missing {sorted(missing)}")
        records.append(record)
    return records


def load_sqlite(all_records, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    connection = sqlite3.connect(destination)
    try:
        connection.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
        connection.executemany(
            "INSERT INTO mandi_prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(
                str(x["source_record_id"]), str(x.get("district_code", "")), x["district"],
                str(x.get("market_code", "")), x["market"], x["date"],
                str(x.get("crop_code", "")), x["crop"], x.get("variety"), x.get("price"),
                x.get("minimum_price"), x.get("maximum_price"), x.get("unit", ""),
                x["source_url"], x.get("extraction_run_id", "missing"),
                x.get("extracting_agent", "missing"), x.get("extracted_at", "missing"),
            ) for x in all_records["mandi_prices"]],
        )
        connection.executemany(
            "INSERT INTO crop_statistics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(
                x["crop"], x["season"], x["year"], x.get("area_hectares"),
                x.get("production"), x.get("yield_kg_per_hectare"),
                x.get("production_unit", ""), x["source_file"], x["source_row"],
                x.get("extraction_run_id"), x.get("extracting_agent"), x.get("extracted_at"),
            ) for x in all_records["crop_statistics"]],
        )
        connection.executemany(
            "INSERT INTO agriculture_documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(
                x["content_hash"], x.get("document_title", ""), x["page_number"],
                x.get("chunk_index", 0), x["content"], x.get("language"),
                x.get("extraction_method"), x["source_url"], x.get("source_file", ""),
                x.get("extraction_run_id"), x.get("extracting_agent"), x.get("extracted_at"),
            ) for x in all_records["agriculture_documents"]],
        )
        location_rows = []
        for x in all_records["mandi_locations"]:
            coordinates = x.get("location", {}).get("coordinates", [])
            if len(coordinates) != 2:
                raise ValueError(f"Invalid GeoJSON coordinates for market {x['market_code']}")
            location_rows.append((
                str(x["market_code"]), x["market_name"], x["district_name"],
                coordinates[0], coordinates[1], x.get("location_precision", ""),
                x["verification_status"], x.get("coordinate_source_url", ""),
            ))
        connection.executemany(
            "INSERT INTO mandi_locations VALUES (?,?,?,?,?,?,?,?)", location_rows
        )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite integrity check failed: {integrity}")
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", default="db/dump")
    parser.add_argument("--sqlite", default="db/dump/agriagent.sqlite")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    folder = ROOT / args.dump
    all_records = {name: read_collection(folder, name) for name in COLLECTIONS}
    for name, records in all_records.items():
        print(f"{name}: {len(records)} valid records")
    if not args.validate_only:
        destination = ROOT / args.sqlite
        load_sqlite(all_records, destination)
        print(f"SQLite mirror loaded: {destination.resolve()}")
    print(f"Total validated: {sum(map(len, all_records.values()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
