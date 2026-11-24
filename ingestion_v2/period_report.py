"""Preview weekly/monthly district summary CSVs without treating them as daily prices."""

import calendar
import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
from io import StringIO

from scripts.export_mandi_period_report import FIELDS


MAX_REPORT_BYTES = 512 * 1024
MAX_REPORT_ROWS = 1000


def _date(value, field):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return parsed
    except ValueError:
        pass
    raise ValueError(f"{field} must be YYYY-MM-DD")


def preview_period_report(payload, frequency):
    if frequency not in {"weekly", "monthly"}:
        raise ValueError("frequency must be weekly or monthly")
    if not 0 < len(payload) <= MAX_REPORT_BYTES:
        raise ValueError("CSV must be nonempty and no larger than 512 KiB")
    reader = csv.DictReader(StringIO(payload.decode("utf-8-sig"), newline=""), strict=True)
    if reader.fieldnames is None or (
        len(reader.fieldnames) != len(FIELDS) or set(reader.fieldnames) != set(FIELDS)
    ):
        raise ValueError("CSV headers must match the documented district period report format")
    rows = []
    identities = set()
    for row in reader:
        if len(rows) >= MAX_REPORT_ROWS:
            raise ValueError("report exceeds 1000 rows")
        if None in row or any(value is None or not value.strip() or len(value) > 300 for value in row.values()):
            raise ValueError(f"line {reader.line_num}: missing, extra or overlong field")
        if row["frequency"] != frequency:
            raise ValueError(f"line {reader.line_num}: report frequency does not match the selected view")
        start = _date(row["period_start"], "period_start")
        as_of = _date(row["evidence_as_of"], "evidence_as_of")
        if as_of < start:
            raise ValueError("evidence_as_of must not precede period_start")
        if frequency == "weekly":
            if start.weekday() != 0:
                raise ValueError("weekly periods must start on Monday")
            end = start + timedelta(days=6)
        else:
            if start.day != 1:
                raise ValueError("monthly periods must start on the first day")
            end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        try:
            price = Decimal(row["average_modal_price_inr"])
        except InvalidOperation as exc:
            raise ValueError("average modal price must be a finite nonnegative decimal") from exc
        if not price.is_finite() or price < 0 or price > Decimal("1000000000") or price.as_tuple().exponent < -8:
            raise ValueError("average modal price must be a finite nonnegative decimal")
        count = row["observation_count"]
        if not count.isascii() or not count.isdecimal() or len(count) > 9 or int(count) < 1:
            raise ValueError("observation_count must be a positive integer")
        identity = (start, row["district"].strip().casefold(), row["crop"].strip().casefold(),
                    row["price_unit"].strip().casefold())
        if identity in identities:
            raise ValueError(f"line {reader.line_num}: duplicate district/crop/unit/period")
        identities.add(identity)
        rows.append({
            **row, "period_end": end.isoformat(), "average_modal_price_inr": format(price, "f"),
            "observation_count": int(count), "source_line": reader.line_num,
        })
    if not rows:
        raise ValueError("report contains no data rows")
    return {
        "frequency": frequency, "count": len(rows), "sha256": hashlib.sha256(payload).hexdigest(),
        "mode": "preview_only", "database_writes": False,
        "rows": sorted(rows, key=lambda row: (row["period_start"], row["district"], row["crop"])),
    }
