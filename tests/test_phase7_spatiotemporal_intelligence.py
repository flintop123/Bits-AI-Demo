import unittest

from services.agriculture_query_service import AgricultureQueryService


class SpatiotemporalIntelligenceTests(unittest.TestCase):
    def test_localization_adds_labels_without_replacing_official_values(self):
        service = AgricultureQueryService.__new__(AgricultureQueryService)

        class Labels:
            translations = {
                "crop": {"आलू": "Potato"},
                "district": {"अरवल": "Arwal"},
                "market": {"अरवल": "Arwal"},
            }

            def options(self, field, values, language):
                return [{
                    "value": value,
                    "label": self.translations[field].get(value, value),
                } for value in values]

        service._catalog_labels = Labels()
        result = {
            "filters": {"crop": "आलू", "district": "अरवल"},
            "market_comparison": [{
                "market": "अरवल", "district": "अरवल"
            }],
        }
        localized = service._localize_market_intelligence(result, "en")
        self.assertEqual(localized["filters"]["crop"], "आलू")
        self.assertEqual(localized["display_filters"]["crop"], "Potato")
        self.assertEqual(
            localized["market_comparison"][0]["market"], "अरवल"
        )
        self.assertEqual(
            localized["market_comparison"][0]["market_label"], "Arwal"
        )

    def test_calculates_change_volatility_rank_and_freshness(self):
        records = []
        for offset, (day, first, second) in enumerate((
            ("2026-10-14", 1000, 1100),
            ("2026-10-15", 1100, 1200),
            ("2026-10-16", 1200, 1300),
            ("2026-10-17", 1300, 1400),
            ("2026-10-18", 1500, 1600),
        )):
            records.extend([
                {
                    "date": day, "district": "Arwal", "district_code": "1",
                    "market": "Market A", "market_code": "A", "crop": "Potato",
                    "price": first, "unit": "quintal",
                    "source_url": "https://example.test/mandi",
                },
                {
                    "date": day, "district": "Arwal", "district_code": "1",
                    "market": "Market B", "market_code": "B", "crop": "Potato",
                    "price": second, "unit": "quintal",
                    "source_url": "https://example.test/mandi",
                },
            ])

        result = AgricultureQueryService._build_market_intelligence(
            records, [], {"crop": "Potato"}, 30,
            dataset_latest="2026-10-18",
        )

        self.assertEqual(result["summary"]["observations"], 10)
        self.assertEqual(result["summary"]["earliest_average_price"], 1050.0)
        self.assertEqual(result["summary"]["latest_average_price"], 1550.0)
        self.assertEqual(result["summary"]["direction"], "rising")
        self.assertAlmostEqual(result["summary"]["change_percent"], 47.62)
        self.assertGreater(result["summary"]["daily_volatility_percent"], 0)
        self.assertEqual(result["market_comparison"][0]["market"], "Market B")
        self.assertEqual(result["market_comparison"][0]["latest_price_rank"], 1)
        self.assertEqual(result["freshness"]["status"], "current")

    def test_nearby_mode_includes_distance_and_verified_scope(self):
        records = [{
            "date": "2026-10-18", "district": "Patna", "market": "Patna",
            "market_code": "PAT", "crop": "Onion", "price": 2200,
            "unit": "quintal",
        }]
        locations = [{
            "market_code": "PAT", "distance_meters": 12500,
            "location_precision": "locality",
        }]

        result = AgricultureQueryService._build_market_intelligence(
            records, locations, {"crop": "Onion"}, 7,
            dataset_latest="2026-10-18", latitude=25.6, longitude=85.1,
            radius_km=50,
        )

        self.assertEqual(result["locality"]["mode"], "nearby_verified_markets")
        self.assertEqual(result["locality"]["verified_markets_in_radius"], 1)
        self.assertEqual(result["market_comparison"][0]["distance_km"], 12.5)

    def test_anomaly_rule_requires_five_dates_and_two_sigma(self):
        records = []
        for day, price in zip(
            ("2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18"),
            (100, 100, 100, 100, 1000),
        ):
            records.append({
                "date": day, "district": "Arwal", "market": "Arwal",
                "market_code": "A", "crop": "Potato", "price": price,
            })

        result = AgricultureQueryService._build_market_intelligence(
            records, [], {"crop": "Potato"}, 7,
            dataset_latest="2026-10-18",
        )

        self.assertEqual(result["summary"]["anomaly_days"], 1)
        self.assertEqual(result["anomalies"][0]["date"], "2026-10-18")
        self.assertEqual(result["anomalies"][0]["direction"], "high")


if __name__ == "__main__":
    unittest.main()
