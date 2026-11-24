"""Read-only local API smoke check for the nearby-market demo."""

import argparse
import json
import math
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen


ENDPOINT = "/api/v1/mandi-prices/nearby"


def _distance_km(lat, lon, market_lat, market_lon):
    radians = math.radians
    a = (
        math.sin(radians(market_lat - lat) / 2) ** 2
        + math.cos(radians(lat)) * math.cos(radians(market_lat))
        * math.sin(radians(market_lon - lon) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


def _coordinate(value, limit):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > limit:
        raise ValueError("invalid latitude or longitude")
    return value


def verify_response(payload, latitude, longitude, radius, limit):
    want_origin = {"type": "Point", "coordinates": [longitude, latitude]}
    if payload.get("origin") != want_origin or payload.get("radius_km") != radius:
        raise ValueError("API response did not echo the expected origin and radius")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != payload.get("count") or len(records) > limit:
        raise ValueError("API response count does not match the records and limit")
    markets = {}
    for record in records:
        code = record.get("market_code")
        if not isinstance(code, (str, int)) or isinstance(code, bool) or code == "":
            raise ValueError("nearby record is missing a market code")
        geometry = record.get("market_location") or {}
        coords = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not isinstance(coords, list) or len(coords) != 2:
            raise ValueError(f"market {code}: expected a GeoJSON Point")
        market_lon, market_lat = _coordinate(coords[0], 180), _coordinate(coords[1], 90)
        distance = record.get("distance_km")
        if type(distance) not in (int, float) or not math.isfinite(distance) or not 0 <= distance <= radius + 0.001:
            raise ValueError(f"market {code}: reported distance outside the requested radius")
        expected = _distance_km(latitude, longitude, market_lat, market_lon)
        # MongoDB and the verifier can use slightly different Earth radii.
        if abs(expected - distance) > max(0.02, expected * 0.002):
            raise ValueError(f"market {code}: distance disagrees with its coordinates")
        key = str(code)
        market = {
            "market_code": code, "market": record.get("market"), "district": record.get("district"),
            "coordinates": [market_lon, market_lat], "distance_km": distance,
        }
        if key in markets and markets[key] != market:
            raise ValueError(f"market {code}: inconsistent location across observations")
        markets[key] = market
    if not markets:
        raise ValueError("no nearby price observations; choose a verified market or wider radius/window")
    return {
        "radius_km": radius, "record_count": len(records), "possibly_truncated": len(records) == limit,
        "markets": sorted(markets.values(), key=lambda m: (m["distance_km"], str(m["market_code"]))),
    }


def run_smoke(base_url, latitude, longitude, small, large, *, days=365, limit=100, fetch=None):
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in ("http", "https") or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment
    ):
        raise ValueError("use the local read-only API URL, without a path or credentials")
    _coordinate(latitude, 90)
    _coordinate(longitude, 180)
    if not 1 <= small < large <= 300:
        raise ValueError("radii must satisfy 1 <= small < large <= 300 km")

    def get_json(url):
        with urlopen(url, timeout=15) as response:
            return json.load(response)

    get = fetch or get_json
    results = []
    for radius in (small, large):
        query = urlencode({
            "latitude": latitude, "longitude": longitude,
            "radius_km": radius, "days": days, "limit": limit,
        })
        payload = get(base_url.rstrip("/") + ENDPOINT + "?" + query)
        results.append(verify_response(payload, latitude, longitude, radius, limit))
    small_codes = {str(m["market_code"]) for m in results[0]["markets"]}
    additional = [
        m for m in results[1]["markets"]
        if str(m["market_code"]) not in small_codes and m["distance_km"] > small + 0.001
    ]
    return {
        "origin": {"latitude": latitude, "longitude": longitude},
        "results": results,
        "additional_markets_beyond_small_radius": additional,
        "demonstrates_radius_expansion": bool(additional),
        "scope": "local read-only price API; not a browser or OpenStreetMap tile check",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--small", type=float, default=1)
    parser.add_argument("--large", type=float, default=75)
    parser.add_argument("--expect-market-code", help="Require this known market at the smaller radius")
    parser.add_argument("--require-expansion", action="store_true",
                        help="Fail when the larger radius returns no additional market outside the smaller one")
    args = parser.parse_args(argv)
    try:
        report = run_smoke(args.base_url, args.latitude, args.longitude, args.small, args.large)
        if args.expect_market_code and not any(
            str(market["market_code"]) == args.expect_market_code
            for market in report["results"][0]["markets"]
        ):
            raise ValueError("the known market is missing from the smaller radius")
        if args.require_expansion and not report["demonstrates_radius_expansion"]:
            raise ValueError("no additional market outside the smaller radius was returned")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "Radius smoke check failed: " + str(exc) + "\n")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
