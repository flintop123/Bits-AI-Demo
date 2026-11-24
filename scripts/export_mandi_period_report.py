"""Export a weekly or monthly district price report from a prepared dashboard snapshot."""

import argparse
import csv
import json
from pathlib import Path

FIELDS = (
    "frequency", "period_start", "district", "crop", "price_unit",
    "average_modal_price_inr", "observation_count", "evidence_as_of",
    "source", "data_scope",
)


def period_rows(snapshot, frequency):
    if frequency not in {"weekly", "monthly"}:
        raise ValueError("frequency must be weekly or monthly")
    district = snapshot["district_trends"]
    entries = district["frequencies"][frequency]
    if not entries or not district.get("crop") or not district.get("unit"):
        raise ValueError("snapshot contains no district price data with a known crop and unit")
    return [
        {
            "frequency": frequency,
            "period_start": item["period_start"],
            "district": item["district"],
            "crop": district["crop"],
            "price_unit": district["unit"],
            "average_modal_price_inr": item["average_modal_price"],
            "observation_count": item["observation_count"],
            "evidence_as_of": district["latest_observation_date"],
            "source": district["source"],
            "data_scope": "committed snapshot; observed records only",
        }
        for item in sorted(entries, key=lambda item: (item["period_start"], item["district"]))
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=Path("docs/data/dashboard_snapshot.json"))
    parser.add_argument("--frequency", choices=("weekly", "monthly"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        rows = period_rows(snapshot, args.frequency)
        # Exclusive creation avoids silent evidence replacement on a repeated run.
        with args.output.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Report not exported: {exc}\n")
    print(f"{len(rows)} {args.frequency} observed district periods written to {args.output}")


if __name__ == "__main__":
    main()
