import unittest

from data_api import create_app, parse_days, parse_float, parse_limit


class FakeQueryService:
    def __init__(self):
        self.mandi_call = None
        self.statistics_call = None
        self.trends_call = None
        self.nearby_call = None
        self.dashboard_call = None

    def health(self):
        return {
            "status": "ok",
            "database": "bihar_agriculture",
            "collections": {
                "mandi_prices": 10,
                "crop_statistics": 4372,
            },
        }

    def find_mandi_prices(self, filters, limit):
        self.mandi_call = (filters, limit)
        return [{"crop": "Potato", "price": 1200.0}]

    def find_crop_statistics(self, filters, limit):
        self.statistics_call = (filters, limit)
        return [{"crop": "Rice", "year": "2024-25"}]

    def find_mandi_trends(self, filters, days):
        self.trends_call = (filters, days)
        return [{"date": "2026-10-18", "average_modal_price": 1200.0}]

    def find_nearby_mandi_prices(
        self, latitude, longitude, radius_km, filters, days, limit
    ):
        self.nearby_call = (
            latitude, longitude, radius_km, filters, days, limit
        )
        return [{"market": "Arwal", "distance_km": 12.5}]

    def list_values(self):
        return {
            "mandi_crops": ["Potato"],
            "districts": ["Arwal"],
            "markets": ["Arwal"],
            "statistical_crops": ["Rice"],
            "seasons": ["Kharif"],
        }

    def dashboard_snapshot(self, days):
        self.dashboard_call = days
        return {
            "window_days": days,
            "summary": {"mandi_records": 6899},
        }


class DataApiTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeQueryService()
        self.client = create_app(self.service).test_client()

    def test_health_reports_collection_counts(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["collections"]["mandi_prices"], 10)
        self.assertEqual(response.json["collections"]["crop_statistics"], 4372)

    def test_mandi_endpoint_passes_filters_and_limit(self):
        response = self.client.get(
            "/api/v1/mandi-prices?district=Arwal&crop=Potato&limit=5"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.service.mandi_call,
            ({"district": "Arwal", "crop": "Potato"}, 5),
        )
        self.assertEqual(response.json["count"], 1)

    def test_statistics_endpoint_passes_filters(self):
        response = self.client.get(
            "/api/v1/crop-statistics?crop=Rice&year=2024-25"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.service.statistics_call,
            ({"crop": "Rice", "year": "2024-25"}, 20),
        )

    def test_mandi_endpoint_accepts_date_range(self):
        response = self.client.get(
            "/api/v1/mandi-prices?date_from=2026-10-01&date_to=2026-10-18"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.service.mandi_call,
            ({
                "date_from": "2026-10-01",
                "date_to": "2026-10-18",
            }, 20),
        )

    def test_mandi_trend_endpoint_passes_locality_and_window(self):
        response = self.client.get(
            "/api/v1/mandi-prices/trends?district=Arwal&crop=Potato&days=14"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.service.trends_call,
            ({"district": "Arwal", "crop": "Potato"}, 14),
        )
        self.assertEqual(response.json["count"], 1)

    def test_invalid_limit_returns_400(self):
        response = self.client.get("/api/v1/mandi-prices?limit=500")
        self.assertEqual(response.status_code, 400)
        self.assertIn("between 1 and 100", response.json["error"])

    def test_nearby_endpoint_passes_coordinates_window_and_crop(self):
        response = self.client.get(
            "/api/v1/mandi-prices/nearby?latitude=25.6&longitude=85.1"
            "&radius_km=75&days=14&crop=Potato&limit=5"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.service.nearby_call,
            (25.6, 85.1, 75.0, {"crop": "Potato"}, 14, 5),
        )
        self.assertEqual(response.json["origin"]["coordinates"], [85.1, 25.6])

    def test_nearby_endpoint_requires_valid_coordinates(self):
        response = self.client.get(
            "/api/v1/mandi-prices/nearby?latitude=not-a-number&longitude=85"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("latitude must be a number", response.json["error"])

    def test_catalog_returns_available_values(self):
        response = self.client.get("/api/v1/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["statistical_crops"], ["Rice"])

    def test_dashboard_endpoint_passes_window(self):
        response = self.client.get("/api/v1/dashboard?days=60")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.dashboard_call, 60)
        self.assertEqual(response.json["summary"]["mandi_records"], 6899)

    def test_dashboard_endpoint_rejects_invalid_window(self):
        response = self.client.get("/api/v1/dashboard?days=500")
        self.assertEqual(response.status_code, 400)
        self.assertIn("between 1 and 365", response.json["error"])

    def test_unknown_endpoint_remains_404(self):
        response = self.client.get("/does-not-exist")
        self.assertEqual(response.status_code, 404)

    def test_parse_limit_rejects_non_integer(self):
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            parse_limit("abc")

    def test_parse_days_enforces_bounded_window(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 365"):
            parse_days("500")

    def test_parse_float_enforces_coordinate_bounds(self):
        with self.assertRaisesRegex(ValueError, "between -90 and 90"):
            parse_float("91", "latitude", -90, 90)


if __name__ == "__main__":
    unittest.main()
