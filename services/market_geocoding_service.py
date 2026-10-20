"""Conservative Nominatim geocoding for Bihar mandi reference data."""

import json
import math
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
BIHAR_BOUNDS = {
    "min_latitude": 24.25,
    "max_latitude": 27.60,
    "min_longitude": 83.25,
    "max_longitude": 88.35,
}
SOURCE_LICENSE = "OpenStreetMap contributors, ODbL 1.0"
GENERIC_MARKET_WORDS = {
    "market", "mandi", "बाजार", "मंडी", "नया", "new", "yard", "apmc",
}
MARKET_LOCALITY_TYPES = {
    "marketplace", "market", "city", "town", "village", "municipality",
    "hamlet", "suburb", "neighbourhood", "quarter",
}
MINIMUM_DISTRICT_SIMILARITY = 0.55


def normalize_place_name(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^\w\u0900-\u097f]+", " ", text, flags=re.UNICODE)
    tokens = [token for token in text.split() if token not in GENERIC_MARKET_WORDS]
    return " ".join(tokens)


def _similarity(left, right):
    left = normalize_place_name(left)
    right = normalize_place_name(right)
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _best_similarity(values, candidate):
    return max((_similarity(value, candidate) for value in values if value), default=0.0)


def _preferred_language(*values):
    return "hi,en" if any(re.search(r"[\u0900-\u097f]", str(value or "")) for value in values) else "en,hi"


def _address_value(address, names):
    for name in names:
        value = address.get(name)
        if value:
            return str(value)
    return ""


def _best_named_value(expected_values, values):
    candidates = [str(value) for value in values if value]
    if not candidates:
        return "", 0.0
    scored = [
        (_best_similarity(expected_values, candidate), candidate)
        for candidate in candidates
    ]
    best = max(scored, key=lambda item: item[0])
    return best[1], best[0]


def simplify_query_name(value):
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(
        r"\b(?:APMC|Agricultural Produce Market Committee|Market Yard|market|mandi)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?:मंडी|बाजार|नया|नई|नवीन)", " ", text)
    return re.sub(r"\s+", " ", text).strip(" ,-()")


def _distance_km(left, right):
    lat1, lon1 = map(math.radians, left)
    lat2, lon2 = map(math.radians, right)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(math.sqrt(value))


class NominatimGeocoder:
    """Rate-limited geocoder with a persistent response cache."""

    def __init__(
        self,
        *,
        endpoint=None,
        user_agent=None,
        contact_email=None,
        minimum_interval=1.1,
        timeout=30,
        cache_path=None,
        opener=None,
        clock=None,
        sleeper=None,
    ):
        self.endpoint = endpoint or NOMINATIM_SEARCH_URL
        self.contact_email = contact_email or os.getenv(
            "NOMINATIM_CONTACT_EMAIL", ""
        )
        self.user_agent = user_agent or os.getenv(
            "NOMINATIM_USER_AGENT",
            "Bits-AI-Demo-Bihar-Mandi-Geocoder/1.0",
        )
        self.minimum_interval = float(minimum_interval)
        self.timeout = int(timeout)
        self.cache_path = Path(cache_path) if cache_path else None
        self.opener = opener or urlopen
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self._last_request_at = None
        self._cache = self._load_cache()

    def geocode_market(self, market):
        observed_name = str(market.get("market") or "").strip()
        district = str(market.get("district") or "").strip()
        names = [(observed_name, district, "official_name")]
        simplified = simplify_query_name(observed_name)
        if simplified and simplified != observed_name:
            names.append((simplified, district, "generic_suffix_removed"))
        alias_names = market.get("geocoding_aliases") or []
        if market.get("geocoding_alias"):
            alias_names = [market["geocoding_alias"], *alias_names]
        alias_district = str(
            market.get("geocoding_query_district") or district
        ).strip()
        for alias in alias_names:
            alias = str(alias or "").strip()
            if alias and alias not in {item[0] for item in names}:
                names.append((alias, alias_district, "reviewed_alias"))

        match_market = dict(market)
        match_market["match_names"] = [item[0] for item in names]
        match_market["match_districts"] = [
            district,
            *(market.get("geocoding_district_aliases") or []),
            alias_district,
        ]
        attempts = []
        preferred_unresolved = None
        query_plans = list(names)
        query_plans.extend(
            (name, "", f"{strategy}_without_district")
            for name, _query_district, strategy in names
        )
        seen_queries = set()
        for name, query_district, strategy in query_plans:
            query = ", ".join(filter(None, (
                name, query_district, "Bihar", "India",
            )))
            if query in seen_queries:
                continue
            seen_queries.add(query)
            language = _preferred_language(name, query_district)
            candidates = self._search(query, language)
            validation_market = dict(match_market)
            validation_market["require_explicit_district"] = not bool(
                query_district
            )
            decision = select_verified_candidate(
                validation_market, candidates
            )
            attempt = {
                "query": query,
                "query_strategy": strategy,
                "accept_language": language,
                "candidate_count": len(candidates),
                "status": decision["status"],
                "reason": decision.get("reason"),
            }
            attempts.append(attempt)
            if decision["status"] == "verified":
                decision.update(attempt)
                decision["query_attempts"] = attempts
                return decision
            if decision.get("reason") == "ambiguous_top_candidates":
                preferred_unresolved = (decision, attempt)

        decision, attempt = preferred_unresolved or (decision, attempt)
        decision.update(attempt)
        decision["query_attempts"] = attempts
        return decision

    def _search(self, query, accept_language=None):
        accept_language = accept_language or _preferred_language(query)
        cache_key = f"{accept_language}|{query}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        self._respect_rate_limit()
        params = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 5,
            "countrycodes": "in",
            "dedupe": 1,
            "accept-language": accept_language,
        }
        if self.contact_email:
            params["email"] = self.contact_email
        request = Request(
            f"{self.endpoint}?{urlencode(params)}",
            headers={"User-Agent": self.user_agent},
        )
        with self.opener(request, timeout=self.timeout) as response:
            candidates = json.loads(response.read().decode("utf-8"))
        if not isinstance(candidates, list):
            raise ValueError("Nominatim response must be a JSON list")
        self._last_request_at = self.clock()
        self._cache[cache_key] = candidates
        self._save_cache()
        return candidates

    def _respect_rate_limit(self):
        if self._last_request_at is None:
            return
        remaining = self.minimum_interval - (
            self.clock() - self._last_request_at
        )
        if remaining > 0:
            self.sleeper(remaining)

    def _load_cache(self):
        if not self.cache_path or not self.cache_path.exists():
            return {}
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self):
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def select_verified_candidate(market, candidates):
    """Return a location only when the result is Bihar-local and unambiguous."""
    scored = []
    for candidate in candidates:
        try:
            latitude = float(candidate["lat"])
            longitude = float(candidate["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (
            BIHAR_BOUNDS["min_latitude"] <= latitude
            <= BIHAR_BOUNDS["max_latitude"]
            and BIHAR_BOUNDS["min_longitude"] <= longitude
            <= BIHAR_BOUNDS["max_longitude"]
        ):
            continue

        address = candidate.get("address") or {}
        state = _address_value(address, ("state", "state_district"))
        if _similarity(state, "Bihar") < 0.75 and "बिहार" not in state:
            continue

        district, district_similarity = _best_named_value(
            market.get("match_districts") or [market.get("district")],
            [
                address.get(name) for name in (
                    "district", "county", "state_district", "city_district",
                )
            ],
        )
        if market.get("require_explicit_district") and not district:
            continue
        if district and district_similarity < MINIMUM_DISTRICT_SIMILARITY:
            continue

        candidate_name, name_similarity = _best_named_value(
            market.get("match_names") or [market.get("market")],
            [
                address.get(name) for name in (
                    "marketplace", "town", "city", "village", "municipality",
                    "hamlet", "suburb", "neighbourhood", "quarter",
                )
            ] + [candidate.get("name")],
        )
        candidate_name = candidate_name or candidate.get("display_name", "")
        place_type = str(candidate.get("type") or "").casefold()
        if place_type not in MARKET_LOCALITY_TYPES:
            continue
        if not name_similarity:
            name_similarity = _best_similarity(
                market.get("match_names") or [market.get("market")],
                candidate_name,
            )
        if name_similarity < 0.60:
            continue

        importance = max(0.0, min(float(candidate.get("importance", 0)), 1.0))
        score = 0.55 + (0.25 * name_similarity)
        score += 0.15 if district_similarity >= 0.75 else 0.0
        score += 0.05 * importance
        scored.append({
            "score": score,
            "candidate": candidate,
            "latitude": latitude,
            "longitude": longitude,
            "district": district,
            "candidate_name": candidate_name,
        })

    scored.sort(key=lambda item: item["score"], reverse=True)
    if not scored:
        return {
            "status": "unresolved",
            "reason": "no_candidate_passed_bihar_name_and_district_checks",
        }
    resolution_reason = "single_verified_candidate"
    if len(scored) > 1 and scored[0]["score"] - scored[1]["score"] < 0.05:
        top = scored[0]
        second = scored[1]
        separation = _distance_km(
            (top["latitude"], top["longitude"]),
            (second["latitude"], second["longitude"]),
        )
        same_name = _similarity(
            top["candidate_name"], second["candidate_name"]
        ) >= 0.85
        if separation <= 5 and same_name:
            resolution_reason = "coincident_named_locality_candidates"
        else:
            return {
                "status": "unresolved",
                "reason": "ambiguous_top_candidates",
                "top_candidates": [
                    _candidate_summary(item) for item in scored[:3]
                ],
            }

    selected = scored[0]
    score = selected["score"]
    candidate = selected["candidate"]
    latitude = selected["latitude"]
    longitude = selected["longitude"]
    matched_district = selected["district"]
    place_type = candidate.get("type")
    return {
        "status": "verified",
        "confidence": round(score, 4),
        "location": {
            "type": "Point",
            "coordinates": [longitude, latitude],
        },
        "display_name": candidate.get("display_name"),
        "matched_district": matched_district or None,
        "osm_type": candidate.get("osm_type"),
        "osm_id": candidate.get("osm_id"),
        "place_type": place_type,
        "location_precision": (
            "market_facility"
            if place_type in {"marketplace", "market"}
            else "market_locality_centroid"
        ),
        "resolution_reason": resolution_reason,
        "top_candidates": [
            _candidate_summary(item) for item in scored[:3]
        ],
    }


def _candidate_summary(item):
    candidate = item["candidate"]
    return {
        "score": round(item["score"], 4),
        "name": item["candidate_name"],
        "district": item["district"] or None,
        "latitude": item["latitude"],
        "longitude": item["longitude"],
        "osm_type": candidate.get("osm_type"),
        "osm_id": candidate.get("osm_id"),
        "place_type": candidate.get("type"),
        "display_name": candidate.get("display_name"),
    }
