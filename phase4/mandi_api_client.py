"""Deterministic client for the public Bihar Krishi mandi API."""

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = (
    "https://www.biharkrishi.in/agent/v1/staticData/"
    "_search?service=agriMarket"
)
PAGE_URL = "https://www.biharkrishi.in/mandi"
ALLOWED_PAGE_SIZES = (10, 25, 50, 100)


class MandiApiError(RuntimeError):
    """Raised when the public mandi API cannot provide a valid page."""


@dataclass(frozen=True)
class MandiPage:
    records: list
    total_count: int
    page_number: int
    page_size: int
    date_from: int
    date_to: int


def day_epoch_range(value):
    """Return the API's inclusive UTC millisecond range for one date."""
    selected = value if isinstance(value, date) else date.fromisoformat(value)
    start = datetime.combine(selected, datetime_time.min, tzinfo=timezone.utc)
    end = datetime.combine(selected, datetime_time.max, tzinfo=timezone.utc)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


class BiharMandiApiClient:
    """Read paginated price observations without browser scraping."""

    def __init__(
        self,
        *,
        endpoint=API_URL,
        timeout=60,
        max_retries=2,
        opener=None,
        sleeper=None,
    ):
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_retries = max_retries
        self.opener = opener or urlopen
        self.sleeper = sleeper or time.sleep

    def fetch_page(self, selected_date, *, page_number=1, page_size=100):
        if page_number < 1:
            raise ValueError("page_number must be at least 1")
        if page_size not in ALLOWED_PAGE_SIZES:
            raise ValueError(
                "page_size must be one of "
                + ", ".join(str(value) for value in ALLOWED_PAGE_SIZES)
            )
        date_from, date_to = day_epoch_range(selected_date)
        payload = {
            "requestBody": {
                "SearchCriteria": {
                    "locale": "hi_IN",
                    "pageNo": page_number,
                    "pageSize": page_size,
                    "dateFrom": date_from,
                    "dateTo": date_to,
                }
            },
            "requestParams": {"tenantId": "br"},
        }
        body = self._post(payload)
        response_info = body.get("ResponseInfo", {})
        if response_info.get("status") not in (None, "successful"):
            raise MandiApiError(
                "The Bihar mandi API returned an unsuccessful status"
            )
        records = body.get("Data")
        total_count = body.get("totalCounts")
        if not isinstance(records, list):
            raise MandiApiError("The Bihar mandi API response has no Data list")
        if not isinstance(total_count, int) or total_count < 0:
            raise MandiApiError(
                "The Bihar mandi API response has an invalid totalCounts"
            )
        outside_range = [
            record.get("id")
            for record in records
            if not isinstance(record, dict)
            or not isinstance(record.get("arrivalDate"), (int, float))
            or not date_from <= record["arrivalDate"] <= date_to
        ]
        if outside_range:
            raise MandiApiError(
                "The date-bounded API response included records outside "
                "the requested day"
            )
        return MandiPage(
            records=records,
            total_count=total_count,
            page_number=page_number,
            page_size=page_size,
            date_from=date_from,
            date_to=date_to,
        )

    def fetch_day(self, selected_date, *, page_size=100, max_pages=1000):
        first = self.fetch_page(
            selected_date, page_number=1, page_size=page_size
        )
        pages = [first]
        page_number = 2
        while sum(len(page.records) for page in pages) < first.total_count:
            if page_number > max_pages:
                raise MandiApiError(
                    f"Safety limit of {max_pages} pages was reached"
                )
            current = self.fetch_page(
                selected_date,
                page_number=page_number,
                page_size=page_size,
            )
            if current.total_count != first.total_count:
                raise MandiApiError(
                    "The total record count changed during pagination"
                )
            if not current.records:
                raise MandiApiError(
                    "Pagination ended before all reported records arrived"
                )
            pages.append(current)
            page_number += 1

        records = []
        seen = set()
        for page in pages:
            for record in page.records:
                identity = record.get("id")
                if not identity:
                    raise MandiApiError("A mandi record has no official id")
                if identity in seen:
                    continue
                seen.add(identity)
                records.append(record)
        if len(records) != first.total_count:
            raise MandiApiError(
                "Unique records do not match the API's reported total"
            )
        return {
            "date": str(selected_date),
            "records": records,
            "total_count": first.total_count,
            "pages_fetched": len(pages),
            "page_size": page_size,
            "date_from": first.date_from,
            "date_to": first.date_to,
        }

    def _post(self, payload):
        encoded = json.dumps(payload).encode("utf-8")
        request = Request(
            self.endpoint,
            data=encoded,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Bits-AI-Demo/Phase4-Mandi-Collector",
            },
            method="POST",
        )
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    status = getattr(response, "status", 200)
                    if status != 200:
                        raise MandiApiError(
                            f"The Bihar mandi API returned HTTP {status}"
                        )
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                last_error = exc
                retryable = exc.code == 429 or exc.code >= 500
                if not retryable or attempt >= self.max_retries:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
            if attempt < self.max_retries:
                self.sleeper(2 ** attempt)
        raise MandiApiError(
            f"Unable to read the Bihar mandi API: {last_error}"
        ) from last_error
