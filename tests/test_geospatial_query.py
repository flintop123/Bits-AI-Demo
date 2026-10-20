import unittest
from unittest.mock import Mock

from services.agriculture_query_service import AgricultureQueryService


class GeospatialQueryTests(unittest.TestCase):
    def test_nearby_query_uses_2dsphere_and_latest_data_window(self):
        service = AgricultureQueryService.__new__(AgricultureQueryService)
        service.mandi_locations = Mock()
        service.mandi_prices = Mock()
        service.mandi_locations.aggregate.return_value = [{
            "market_code": 10026,
            "location": {"type": "Point", "coordinates": [85.53, 25.36]},
            "distance_meters": 12500,
            "coordinate_source": "OpenStreetMap Nominatim",
            "coordinate_source_url": "https://nominatim.openstreetmap.org/search",
            "coordinate_source_license": "OpenStreetMap contributors, ODbL 1.0",
            "confidence": 0.9,
            "location_precision": "market_locality_centroid",
        }]
        service.mandi_prices.find_one.return_value = {"date": "2026-10-18"}
        cursor = Mock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = [{
            "market_code": 10026,
            "date": "2026-10-18",
            "crop": "आलू",
            "price": 1200,
        }]
        service.mandi_prices.find.return_value = cursor

        result = service.find_nearby_mandi_prices(
            25.6, 85.1, 50, {"crop": "आलू"}, 7, 20
        )

        geo_stage = service.mandi_locations.aggregate.call_args.args[0][0]
        self.assertEqual(
            geo_stage["$geoNear"]["near"]["coordinates"], [85.1, 25.6]
        )
        self.assertEqual(geo_stage["$geoNear"]["maxDistance"], 50000)
        price_query = service.mandi_prices.find.call_args.args[0]
        self.assertEqual(
            price_query["date"],
            {"$gte": "2026-10-12", "$lte": "2026-10-18"},
        )
        self.assertEqual(result[0]["distance_km"], 12.5)
        self.assertEqual(
            result[0]["market_location"]["coordinates"], [85.53, 25.36]
        )
        self.assertEqual(
            result[0]["coordinate_provenance"]["precision"],
            "market_locality_centroid",
        )

    def test_no_nearby_locations_returns_no_prices(self):
        service = AgricultureQueryService.__new__(AgricultureQueryService)
        service.mandi_locations = Mock()
        service.mandi_prices = Mock()
        service.mandi_locations.aggregate.return_value = []
        result = service.find_nearby_mandi_prices(
            25.6, 85.1, 50, {}, 7, 20
        )
        self.assertEqual(result, [])
        service.mandi_prices.find.assert_not_called()


if __name__ == "__main__":
    unittest.main()
