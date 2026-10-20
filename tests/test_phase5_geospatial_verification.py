import unittest

from verify_phase5_geospatial import (
    validate_dry_run,
    validate_duplicate_check,
    validate_indexes,
    validate_location_record,
)


def location(code=1):
    return {
        "market_code": code,
        "market_name": f"Market {code}",
        "district_name": "Patna",
        "location": {"type": "Point", "coordinates": [85.1, 25.6]},
        "verification_status": "verified",
        "location_precision": "market_locality_centroid",
        "confidence": 0.9,
        "coordinate_source": "OpenStreetMap Nominatim",
        "coordinate_source_url": "https://nominatim.openstreetmap.org/search",
        "coordinate_source_license": "OpenStreetMap contributors, ODbL 1.0",
    }


class Phase5GeospatialVerificationTests(unittest.TestCase):
    def test_location_outside_bihar_is_rejected(self):
        record = location()
        record["location"]["coordinates"] = [77.2, 28.6]
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_location_record(record)

    def test_dry_run_requires_rejected_cross_district_market(self):
        report = {
            "dry_run": True,
            "markets_considered": 49,
            "verified": 42,
            "unresolved": 7,
            "already_geocoded": 0,
            "verified_locations": [location(code) for code in range(1, 43)],
            "unresolved_markets": [
                {"market_code": code} for code in range(100, 107)
            ],
        }
        with self.assertRaisesRegex(ValueError, "Bhagwanpur"):
            validate_dry_run(report)

    def test_duplicate_check_must_not_write(self):
        report = {
            "dry_run": False,
            "markets_considered": 49,
            "verified": 0,
            "unresolved": 7,
            "already_geocoded": 42,
            "database_write": {"inserted": 1, "matched": 0, "modified": 0},
        }
        with self.assertRaisesRegex(ValueError, "unexpectedly wrote"):
            validate_duplicate_check(report)

    def test_required_indexes_are_accepted(self):
        validate_indexes({
            "unique_mandi_market_code": {
                "key": [("market_code", 1)],
                "unique": True,
            },
            "mandi_location_2dsphere": {
                "key": [("location", "2dsphere")],
            },
        })


if __name__ == "__main__":
    unittest.main()
