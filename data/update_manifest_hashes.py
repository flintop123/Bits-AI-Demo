"""Update local corpus SHA-256 values without downloading or altering sources."""

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifest.csv"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    with MANIFEST.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    for row in rows:
        location = row["corpus_path_or_endpoint"]
        if location == "live API":
            row["sha256_status"] = "not_applicable_live_endpoint"
            continue
        path = ROOT / location
        row["sha256_status"] = sha256(path) if path.is_file() else "not_available_locally"
    with MANIFEST.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(rows)
    print(f"Manifest hashes updated: {MANIFEST}")


if __name__ == "__main__":
    main()
