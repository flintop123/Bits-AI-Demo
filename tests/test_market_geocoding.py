import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

from pymongo import ASCENDING, GEOSPHERE

from conn.mandi_locations import MandiLocationMongo
from services.market_geocoding_service import (
    NominatimGeocoder,
    select_verified_candidate,
    simplify_query_name,
)


MARKET = {
    "market_code": 10026,
    "market": "हरनौत (नया)",
    "district": "नालन्दा",
    "district_code": "229",
}


def candidate(**overrides):
    value = {
        "lat": "25.3681",
        "lon": "85.5314",
        "importance": 0.35,
        "display_name": "हरनौत, नालन्दा, बिहार, भारत",
        "name": "हरनौत",
        "osm_type": "node",
        "osm_id": 123,
        "type": "town",
        "address": {
            "town": "हरनौत",
            "state_district": "नालन्दा",
            "state": "बिहार",
        },
    }
    value.update(overrides)
    return value


class CandidateSelectionTests(unittest.TestCase):
    def test_verified_candidate_uses_geojson_longitude_first(self):
        result = select_verified_candidate(MARKET, [candidate()])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(
            result["location"],
            {"type": "Point", "coordinates": [85.5314, 25.3681]},
        )

    def test_candidate_outside_bihar_is_rejected(self):
        result = select_verified_candidate(
            MARKET, [candidate(lat="28.6139", lon="77.2090")]
        )
        self.assertEqual(result["status"], "unresolved")

    def test_administrative_district_centroid_is_not_a_market_location(self):
        administrative = candidate(type="county")
        result = select_verified_candidate(MARKET, [administrative])
        self.assertEqual(result["status"], "unresolved")

    def test_reviewed_cross_script_name_and_district_can_match(self):
        english = candidate(name="Daudnagar", type="town")
        english["address"]["town"] = "Daudnagar"
        english["address"]["state_district"] = "Aurangabad"
        market = {
            **MARKET,
            "market": "दाउनगर",
            "district": "औरंगाबाद",
            "match_names": ["दाउनगर", "दाउदनगर", "Daudnagar"],
            "match_districts": ["औरंगाबाद", "Aurangabad"],
        }
        result = select_verified_candidate(market, [english])
        self.assertEqual(result["status"], "verified")

    def test_explicit_district_mismatch_is_rejected(self):
        wrong = candidate()
        wrong["address"]["state_district"] = "पटना"
        result = select_verified_candidate(MARKET, [wrong])
        self.assertEqual(result["status"], "unresolved")

    def test_similar_subdistrict_name_cannot_replace_wrong_district(self):
        wrong = candidate(
            name="Bhagwanpur",
            display_name="Bhagwanpur, Vaishali, Bihar, India",
        )
        wrong["address"] = {
            "town": "Bhagwanpur",
            "county": "Bhagwanpur",
            "state_district": "Vaishali",
            "state": "Bihar",
        }
        market = {
            **MARKET,
            "market": "भगवानपुर मंडी (नई)",
            "district": "मुजफ्फरपुर",
            "match_names": ["भगवानपुर", "Bhagwanpur"],
            "match_districts": ["मुजफ्फरपुर", "Muzaffarpur"],
            "require_explicit_district": True,
        }
        result = select_verified_candidate(market, [wrong])
        self.assertEqual(result["status"], "unresolved")

    def test_minor_hindi_district_spelling_difference_is_accepted(self):
        value = candidate()
        value["address"]["state_district"] = "नालंदा जिला"
        result = select_verified_candidate(MARKET, [value])
        self.assertEqual(result["status"], "verified")

    def test_close_top_candidates_are_left_unresolved(self):
        other = candidate(
            osm_id=456,
            importance=0.34,
            lat="26.1000",
            lon="86.9000",
        )
        result = select_verified_candidate(MARKET, [candidate(), other])
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["reason"], "ambiguous_top_candidates")

    def test_non_locality_station_candidate_does_not_create_ambiguity(self):
        other = candidate(
            osm_id=456,
            importance=0.34,
            lat="25.3690",
            lon="85.5320",
            type="administrative",
        )
        result = select_verified_candidate(MARKET, [candidate(), other])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["resolution_reason"], "single_verified_candidate")
        self.assertEqual(result["location_precision"], "market_locality_centroid")

    def test_apmc_suffix_can_be_removed_for_fallback_search(self):
        self.assertEqual(simplify_query_name("Samastipur APMC"), "Samastipur")

    def test_hindi_market_suffix_and_parenthetical_label_are_removed(self):
        self.assertEqual(simplify_query_name("मानसी मंडी (नया)"), "मानसी")

    def test_best_district_field_is_used_instead_of_division(self):
        value = candidate()
        value["address"]["state_district"] = "पटना प्रमंडल"
        value["address"]["county"] = "नालन्दा"
        result = select_verified_candidate(MARKET, [value])
        self.assertEqual(result["status"], "verified")

    def test_relaxed_query_requires_an_explicit_matching_district(self):
        value = candidate()
        value["address"].pop("state_district")
        market = {**MARKET, "require_explicit_district": True}
        result = select_verified_candidate(market, [value])
        self.assertEqual(result["status"], "unresolved")


class NominatimClientTests(unittest.TestCase):
    def test_cached_response_avoids_second_network_call(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps([candidate()]).encode("utf-8")
        opener = Mock(return_value=response)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            client = NominatimGeocoder(
                cache_path=cache,
                opener=opener,
                minimum_interval=0,
            )
            first = client.geocode_market(MARKET)
            second = client.geocode_market(MARKET)
        self.assertEqual(first["status"], "verified")
        self.assertEqual(second["status"], "verified")
        self.assertEqual(opener.call_count, 1)


class MandiLocationMongoTests(unittest.TestCase):
    def test_indexes_include_unique_code_and_2dsphere(self):
        database = SimpleNamespace(client=Mock())
        collection = Mock()
        database.__getitem__ = Mock(return_value=collection)
        store = MandiLocationMongo.__new__(MandiLocationMongo)
        store.collection = collection
        store._ensure_indexes()
        collection.create_index.assert_has_calls([
            call(
                [("market_code", ASCENDING)],
                unique=True,
                name="unique_mandi_market_code",
            ),
            call([("location", GEOSPHERE)], name="mandi_location_2dsphere"),
            call(
                [("district_code", ASCENDING), ("market_name", ASCENDING)],
                name="mandi_location_district",
            ),
        ])

    def test_unverified_locations_cannot_be_written(self):
        store = MandiLocationMongo.__new__(MandiLocationMongo)
        store.collection = Mock()
        with self.assertRaisesRegex(ValueError, "Only verified"):
            store.upsert_verified([{
                "market_code": 1,
                "verification_status": "unresolved",
            }])

    def test_verified_location_requires_explicit_precision(self):
        store = MandiLocationMongo.__new__(MandiLocationMongo)
        store.collection = Mock()
        with self.assertRaisesRegex(ValueError, "location_precision"):
            store.upsert_verified([{
                "market_code": 1,
                "verification_status": "verified",
                "location": {"type": "Point", "coordinates": [85, 25]},
            }])


if __name__ == "__main__":
    unittest.main()
