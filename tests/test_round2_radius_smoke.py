from urllib.parse import parse_qs, urlsplit
import unittest

from scripts.verify_round2_radius import run_smoke, verify_response


class RadiusSmokeTests(unittest.TestCase):
    @staticmethod
    def payload(radius, records):
        return {
            "origin": {"type": "Point", "coordinates": [85, 25]},
            "radius_km": radius, "count": len(records), "records": records,
        }

    @staticmethod
    def row(code, latitude, distance):
        return {
            "market_code": code, "market_location": {"type": "Point", "coordinates": [85, latitude]},
            "distance_km": distance,
        }

    def test_two_radii_can_find_another_market(self):
        def fetch(url):
            radius = float(parse_qs(urlsplit(url).query)["radius_km"][0])
            rows = [self.row("A", 25, 0)]
            if radius > 20:
                rows.append(self.row("B", 25.3, 33.36))
            return self.payload(radius, rows)

        result = run_smoke("http://127.0.0.1:5000", 25, 85, 15, 70, fetch=fetch)
        self.assertTrue(result["demonstrates_radius_expansion"])
        self.assertEqual(result["additional_markets_beyond_small_radius"][0]["market_code"], "B")

    def test_rejects_coordinates_inconsistent_with_reported_distance(self):
        with self.assertRaisesRegex(ValueError, "disagrees"):
            verify_response(self.payload(70, [self.row("A", 25.3, 2)]), 25, 85, 70, 100)

    def test_rejects_result_beyond_radius(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            verify_response(self.payload(15, [self.row("A", 25.3, 33.36)]), 25, 85, 15, 100)

    def test_no_markets_is_not_an_implicitly_passing_demo(self):
        with self.assertRaisesRegex(ValueError, "no nearby"):
            verify_response(self.payload(15, []), 25, 85, 15, 100)
