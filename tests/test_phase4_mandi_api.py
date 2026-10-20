import io
import json
import unittest
from datetime import date

from phase4.mandi_api_client import (
    BiharMandiApiClient,
    MandiApiError,
    day_epoch_range,
)


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class MandiApiClientTests(unittest.TestCase):
    def test_day_epoch_range_is_one_inclusive_utc_day(self):
        start, end = day_epoch_range(date(2026, 10, 18))
        self.assertEqual(start, 1792281600000)
        self.assertEqual(end, 1792367999999)

    def test_fetch_page_uses_verified_api_contract(self):
        captured = {}

        def opener(request, timeout):
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return FakeResponse({
                "ResponseInfo": {"status": "successful"},
                "Data": [{"id": "one", "arrivalDate": 1792281600000}],
                "totalCounts": 1,
            })

        page = BiharMandiApiClient(opener=opener).fetch_page(
            "2026-10-18", page_size=100
        )
        criteria = captured["payload"]["requestBody"]["SearchCriteria"]
        self.assertEqual(criteria["dateFrom"], 1792281600000)
        self.assertEqual(criteria["dateTo"], 1792367999999)
        self.assertEqual(criteria["pageNo"], 1)
        self.assertEqual(criteria["pageSize"], 100)
        self.assertEqual(len(page.records), 1)

    def test_fetch_day_paginates_and_preserves_unique_records(self):
        calls = []

        def opener(request, timeout):
            payload = json.loads(request.data)
            page = payload["requestBody"]["SearchCriteria"]["pageNo"]
            calls.append(page)
            values = {
                1: [
                    {"id": "one", "arrivalDate": 1792281600000},
                    {"id": "two", "arrivalDate": 1792281600000},
                ],
                2: [{"id": "three", "arrivalDate": 1792281600000}],
            }
            return FakeResponse({
                "ResponseInfo": {"status": "successful"},
                "Data": values[page],
                "totalCounts": 3,
            })

        result = BiharMandiApiClient(opener=opener).fetch_day(
            "2026-10-18", page_size=10
        )
        self.assertEqual(calls, [1, 2])
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(len(result["records"]), 3)

    def test_out_of_range_record_is_rejected(self):
        client = BiharMandiApiClient(opener=lambda *_args, **_kwargs: FakeResponse({
            "ResponseInfo": {"status": "successful"},
            "Data": [{"id": "old", "arrivalDate": 1792195200000}],
            "totalCounts": 1,
        }))
        with self.assertRaisesRegex(MandiApiError, "outside"):
            client.fetch_page("2026-10-18")


if __name__ == "__main__":
    unittest.main()
