"""
Google Maps API client wrapper.

Implements legacy Geocoding plus Routes API (``computeRoutes``) for directions.
The Routes implementation is intentionally minimal: we request only the fields
needed for summary style answers to keep latency and payload size low.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import async_timeout

if TYPE_CHECKING:
    import aiohttp

from ..const import HTTP_TIMEOUT
from .const import (
    GEOCODE_ENDPOINT,
    PLACES_DETAILS_ENDPOINT,
    PLACES_FIELD_MASK_DETAILS,
    PLACES_FIELD_MASK_SEARCH_NEARBY,
    PLACES_FIELD_MASK_SEARCH_TEXT,
    PLACES_NEARBY_SEARCH_ENDPOINT,
    PLACES_TEXT_SEARCH_ENDPOINT,
    PRICE_LEVEL_MAP,
    ROUTES_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


class GoogleMapsApiError(Exception):
    """General Google Maps API error."""


class GoogleMapsAuthError(GoogleMapsApiError):
    """Authentication / authorization error."""


def _rfc3339(ts: int) -> str:
    """Return RFC3339 UTC timestamp for an epoch seconds value."""
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class DirectionsOptions:
    """Container for directions options to keep function signatures small."""

    mode: str | None = None
    language: str | None = None
    region: str | None = None
    alternatives: bool | None = None
    units: str | None = None
    departure_time: int | None = None
    arrival_time: int | None = None
    avoid: str | None = None


def _build_routes_body(
    origin: str, destination: str, options: DirectionsOptions
) -> dict[str, Any]:
    """Build request body for computeRoutes from legacy style arguments."""
    body: dict[str, Any] = {
        "origin": {"address": origin},
        "destination": {"address": destination},
    }
    if options.mode:
        mode_map = {
            "driving": "DRIVE",
            "walking": "WALK",
            "bicycling": "BICYCLE",
            "transit": "TRANSIT",
        }
        body["travelMode"] = mode_map.get(options.mode, "DRIVE")
    if options.alternatives:
        body["computeAlternativeRoutes"] = True
    # Mutually exclusive: prefer departure_time if both provided
    dep = options.departure_time
    arr = options.arrival_time
    if dep is not None and arr is not None:
        arr = None
    if dep is not None:
        body["departureTime"] = _rfc3339(dep)
    elif arr is not None and body.get("travelMode") == "TRANSIT":
        body["arrivalTime"] = _rfc3339(arr)
    if options.language:
        body["languageCode"] = options.language
    if options.region:
        body["regionCode"] = options.region
    if options.units:
        body["units"] = (
            options.units.upper()
            if options.units in ("metric", "imperial")
            else options.units
        )
    if options.avoid:
        parts = {p.strip() for p in options.avoid.split("|") if p.strip()}
        mapping = {
            "avoidTolls": {"toll", "tolls"},
            "avoidHighways": {"highway", "highways"},
            "avoidFerries": {"ferry", "ferries"},
        }
        modifiers = {key: True for key, triggers in mapping.items() if parts & triggers}
        if modifiers:
            body["routeModifiers"] = modifiers
    return body


def _routes_field_mask() -> str:
    """Return a compact field mask for computeRoutes requests."""
    parts = [
        "routes.distanceMeters",
        "routes.duration",
        "routes.description",
        "routes.localizedValues",
        "routes.legs.distanceMeters",
        "routes.legs.steps",
        "routes.legs.duration",
        "routes.legs.localizedValues",
    ]
    return ",".join(parts)


def _collapse_objects(node: Any) -> Any:
    """
    Recursively collapse any mapping with a single key to its value.

    Mutates the original structure in-place for lists and dictionaries while
    returning the possibly collapsed value so parents can update references.

    Examples:
        {"staticDuration": {"text": "1 min"}} -> {"staticDuration": "1 min"}
        {"a": {"b": {"c": 1}}} -> {"a": 1}

    """
    if isinstance(node, dict):
        # First collapse children so we mutate in place
        for k, v in list(node.items()):
            node[k] = _collapse_objects(v)
        if len(node) == 1:  # Single key mapping -> replace with its value
            return next(iter(node.values()))
        return node
    if isinstance(node, list):
        for idx, item in enumerate(node):
            node[idx] = _collapse_objects(item)
        return node
    return node


def _apply_localization(
    node: Any,
) -> None:
    """
    Promote localized string values to their parent objects.

    For any mapping containing a ``localizedValues`` dictionary, copy or replace
    fields on the parent with the human friendly string values. Special handling
    is applied for ``distance`` which replaces ``distanceMeters`` (removing the
    numeric meter value entirely). Existing raw duration / staticDuration values
    (e.g. ``1165s`` / ``5s``) are replaced with their localized counterparts
    (e.g. ``19 mins`` / ``1 min``).

    The original ``localizedValues`` container is preserved so callers can still
    access the raw grouping if desired.
    """
    if isinstance(node, dict):
        # If localizedValues present, overlay its values
        if (lv := node.get("localizedValues")) and isinstance(lv, dict):
            # distanceMeters -> distance (replace & remove numeric meters)
            if "distance" in lv and "distanceMeters" in node:
                node.pop("distanceMeters", None)
                node["distance"] = lv["distance"]
            # For the remaining keys just replace/insert
            for key in ("duration", "staticDuration"):
                if key in lv:
                    node[key] = lv[key]
            # Any other localized keys we haven't explicitly handled -> copy if absent
            for key, value in lv.items():
                if (
                    key not in ("distance", "duration", "staticDuration")
                    and key not in node
                ):
                    node[key] = value
        # Recurse into child values
        for v in list(node.values()):
            _apply_localization(v)
    elif isinstance(node, list):
        for item in node:
            _apply_localization(item)


def _remove_polylines(node: Any) -> None:
    """
    Recursively remove any 'polyline' keys from a nested structure.

    The Routes API step objects include an encoded ``polyline`` field which can
    be sizable. For post-processing / summarization use cases we don't need to
    retain this geometry, so we strip it after other transformations to reduce
    payload size and avoid accidentally exposing it downstream.
    """
    if isinstance(node, dict):
        if "polyline" in node:
            node.pop("polyline", None)
        for value in list(node.values()):
            _remove_polylines(value)
    elif isinstance(node, list):
        for item in node:
            _remove_polylines(item)


class GoogleMapsApiClient:
    """Client for Google Maps Web Service endpoints needed for tools."""

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        """
        Initialize the Google Maps API client.

        Args:
            api_key: API key used for Google Maps requests.
            session: An aiohttp.ClientSession used to perform HTTP calls.

        """
        self._api_key = api_key
        self._session = session

    async def geocode(
        self,
        address: str | None = None,
        *,
        components: str | None = None,
        language: str | None = None,
        region: str | None = None,
        bounds: str | None = None,
    ) -> dict[str, Any]:
        """
        Perform a geocoding request.

        Either `address` or `components` (or both) can be provided to filter
        the geocoding results.

        Args:
            address: Full address string to geocode.
            components: Component filters as a string (e.g. 'country:US').
            language: Preferred language for results (e.g. 'en').
            region: Region code to bias results.
            bounds: Bounding box to bias results.

        Returns:
            Parsed JSON response from the Google Maps Geocoding API.

        Raises:
            GoogleMapsApiError: On API errors.
            GoogleMapsAuthError: On authentication issues.

        """
        params: dict[str, Any] = {"key": self._api_key}
        if address:
            params["address"] = address
        if components:
            params["components"] = components
        if language:
            params["language"] = language
        if region:
            params["region"] = region
        if bounds:
            params["bounds"] = bounds
        return await self._request(GEOCODE_ENDPOINT, params)

    async def reverse_geocode(
        self,
        lat: float,
        lng: float,
        *,
        language: str | None = None,
        result_type: str | None = None,
        location_type: str | None = None,
    ) -> dict[str, Any]:
        """
        Get address details for a latitude/longitude coordinate.

        Args:
            lat: Latitude coordinate
            lng: Longitude coordinate
            language: Language code for results (e.g. 'en')
            result_type: Filter results to specified types
            location_type: Filter results by location type

        Returns:
            Dictionary containing geocoding results

        Raises:
            GoogleMapsApiError: On API errors
            GoogleMapsAuthError: On authentication issues

        """
        params: dict[str, Any] = {"latlng": f"{lat},{lng}", "key": self._api_key}
        if language:
            params["language"] = language
        if result_type:
            params["result_type"] = result_type
        if location_type:
            params["location_type"] = location_type
        return await self._request(GEOCODE_ENDPOINT, params)

    async def directions(
        self, origin: str, destination: str, options: DirectionsOptions
    ) -> dict[str, Any]:
        """Call the Routes API ``computeRoutes`` endpoint and return raw JSON."""
        body = _build_routes_body(origin, destination, options)
        field_mask = _routes_field_mask()
        try:
            async with async_timeout.timeout(HTTP_TIMEOUT):
                headers = {
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": field_mask,
                    "Content-Type": "application/json",
                }
                async with self._session.post(
                    ROUTES_ENDPOINT, json=body, headers=headers
                ) as resp:
                    if resp.status in (401, 403):
                        msg = "Authentication error with Google Routes API"
                        raise GoogleMapsAuthError(msg)
                    if resp.status != 200:  # noqa: PLR2004 (explicit status check)
                        text = await resp.text()
                        msg = f"Routes API HTTP {resp.status}: {text[:300]}"
                        raise GoogleMapsApiError(msg)
                    data: dict[str, Any] = await resp.json()
                    # Post process data for LLM consumption
                    _remove_polylines(data)
                    _apply_localization(data)
                    _collapse_objects(data)
        except GoogleMapsApiError:
            raise
        except Exception as err:  # pylint: disable=broad-except
            msg = f"Routes request failed: {err}"
            raise GoogleMapsApiError(msg) from err
        if "routes" not in data:
            msg = "Routes API malformed response: missing routes"
            raise GoogleMapsApiError(msg)
        _LOGGER.debug("Routes API response: %s", data)
        return data

    # ------------------------------------------------------------------
    # Places API helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_price_level(value: str | None) -> dict[str, Any] | None:
        """Return mapping with numeric and label for price level."""
        if not value:
            return None
        lvl = PRICE_LEVEL_MAP.get(value)
        if lvl is None:
            return {"label": value}
        return {"level": lvl, "label": value}

    @staticmethod
    def _flatten_place_basic(place: dict[str, Any]) -> dict[str, Any]:
        """Return simplified place object from search responses."""
        out: dict[str, Any] = {}
        pid = place.get("id")
        if pid:
            out["id"] = pid
        dn = place.get("displayName")
        if dn and isinstance(dn, dict):
            out["name"] = dn.get("text")
            lang = dn.get("languageCode")
            if lang is not None:
                out["name_lang"] = lang
        if addr := place.get("formattedAddress"):
            out["address"] = addr
        if ptype := place.get("primaryType"):
            out["primary_type"] = ptype
        if rating := place.get("rating"):
            out["rating"] = rating
        if pl := GoogleMapsApiClient._normalize_price_level(place.get("priceLevel")):
            out["price_level"] = pl
        # openNow nested under currentOpeningHours
        open_now = place.get("currentOpeningHours", {}).get("openNow")
        if open_now is not None:
            out["open_now"] = open_now
        if types := place.get("types"):
            out["types"] = types
        return out

    @staticmethod
    def _simplify_details(place: dict[str, Any]) -> dict[str, Any]:
        """Return simplified place details mapping."""
        out = GoogleMapsApiClient._flatten_place_basic(place)
        # Add phones
        phone_national = place.get("nationalPhoneNumber")
        phone_international = place.get("internationalPhoneNumber")
        if phone_national or phone_international:
            phone: dict[str, Any] = {}
            if phone_national:
                phone["national"] = phone_national
            if phone_international:
                phone["international"] = phone_international
            out["phone"] = phone
        if (website := place.get("websiteUri")) is not None:
            out["website"] = website
        if (urc := place.get("userRatingCount")) is not None:
            out["user_rating_count"] = urc
        # Opening hours weekday descriptions
        weekday_desc = (
            place.get("currentOpeningHours", {}).get("weekdayDescriptions") or []
        )
        if weekday_desc:
            out["hours_weekday_text"] = weekday_desc
        return out

    async def _places_post(
        self, url: str, body: dict[str, Any], field_mask: str
    ) -> dict[str, Any]:
        """Post to Places search endpoint and return JSON."""
        try:
            async with async_timeout.timeout(HTTP_TIMEOUT):
                headers = {
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": field_mask,
                    "Content-Type": "application/json",
                }
                async with self._session.post(url, json=body, headers=headers) as resp:
                    if resp.status != 200:  # noqa: PLR2004
                        text = await resp.text()
                        msg = f"Places API HTTP {resp.status}: {text[:300]}"
                        raise GoogleMapsApiError(msg)
                    data: dict[str, Any] = await resp.json()
        except GoogleMapsApiError:
            raise
        except Exception as err:  # pylint: disable=broad-except
            msg = f"Places request failed: {err}"
            raise GoogleMapsApiError(msg) from err
        return data

    # Dataclasses for options kept here to avoid extra module clutter
    @dataclass(slots=True)
    class TextSearchOptions:
        """Container for text search options."""

        text_query: str
        included_type: str | None = None
        strict_type_filtering: bool | None = None
        open_now: bool | None = None
        min_rating: float | None = None
        price_levels: list[str] | None = None
        radius_m: int | None = None
        bias_center: tuple[float, float] | None = None
        language: str | None = None
        region: str | None = None
        page_size: int | None = None

    @dataclass(slots=True)
    class NearbySearchOptions:
        """Container for nearby search options."""

        radius_m: int
        center: tuple[float, float]
        included_types: list[str] | None = None
        excluded_types: list[str] | None = None
        included_primary_types: list[str] | None = None
        excluded_primary_types: list[str] | None = None
        language: str | None = None
        region: str | None = None
        max_results: int | None = None
        rank: str | None = None

    async def places_search_text(self, options: TextSearchOptions) -> dict[str, Any]:
        """Perform Text Search (New) with fixed field mask and simplification."""
        body: dict[str, Any] = {"textQuery": options.text_query}
        if options.included_type:
            body["includedType"] = options.included_type
        if options.strict_type_filtering is not None:
            body["strictTypeFiltering"] = options.strict_type_filtering
        if options.open_now is not None:
            body["openNow"] = options.open_now
        if options.min_rating is not None:
            body["minRating"] = options.min_rating
        if options.price_levels:
            body["priceLevels"] = options.price_levels
        if options.language:
            body["languageCode"] = options.language
        if options.region:
            body["regionCode"] = options.region
        if options.page_size:
            body["pageSize"] = options.page_size
        if options.radius_m and options.radius_m > 0 and options.bias_center:
            body["locationBias"] = {
                "circle": {
                    "center": {
                        "latitude": options.bias_center[0],
                        "longitude": options.bias_center[1],
                    },
                    "radius": float(options.radius_m),
                }
            }
        data = await self._places_post(
            PLACES_TEXT_SEARCH_ENDPOINT, body, PLACES_FIELD_MASK_SEARCH_TEXT
        )
        places: list[dict[str, Any]] = [
            self._flatten_place_basic(p) for p in data.get("places", [])
        ]
        return {"places": places, "raw_count": len(places)}

    async def places_search_nearby(
        self, options: NearbySearchOptions
    ) -> dict[str, Any]:
        """Perform Nearby Search (New)."""
        body: dict[str, Any] = {
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": options.center[0],
                        "longitude": options.center[1],
                    },
                    "radius": float(options.radius_m),
                }
            }
        }
        if options.included_types:
            body["includedTypes"] = options.included_types
        if options.excluded_types:
            body["excludedTypes"] = options.excluded_types
        if options.included_primary_types:
            body["includedPrimaryTypes"] = options.included_primary_types
        if options.excluded_primary_types:
            body["excludedPrimaryTypes"] = options.excluded_primary_types
        if options.language:
            body["languageCode"] = options.language
        if options.region:
            body["regionCode"] = options.region
        if options.max_results:
            body["maxResultCount"] = options.max_results
        if options.rank:
            body["rankPreference"] = options.rank
        data = await self._places_post(
            PLACES_NEARBY_SEARCH_ENDPOINT, body, PLACES_FIELD_MASK_SEARCH_NEARBY
        )
        places: list[dict[str, Any]] = [
            self._flatten_place_basic(p) for p in data.get("places", [])
        ]
        return {"places": places, "raw_count": len(places)}

    async def place_details(
        self,
        place_id: str,
        *,
        language: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Fetch place details with fixed field mask and simplify."""
        # Accept resource name 'places/<id>' or raw id
        pid = place_id.split("/")[-1]
        url = PLACES_DETAILS_ENDPOINT.format(pid)
        try:
            async with async_timeout.timeout(HTTP_TIMEOUT):
                headers = {
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": PLACES_FIELD_MASK_DETAILS,
                    "Content-Type": "application/json",
                }
                params: dict[str, Any] = {}
                if language:
                    params["languageCode"] = language
                if region:
                    params["regionCode"] = region
                async with self._session.get(
                    url, headers=headers, params=params
                ) as resp:
                    if resp.status in (401, 403):
                        msg = "Authentication error with Google Place Details API"
                        raise GoogleMapsAuthError(msg)
                    if resp.status == 404:  # noqa: PLR2004
                        return {
                            "error": {
                                "code": "NOT_FOUND",
                                "message": "Place not found",
                            }
                        }
                    if resp.status != 200:  # noqa: PLR2004
                        text = await resp.text()
                        msg = f"Place Details HTTP {resp.status}: {text[:300]}"
                        raise GoogleMapsApiError(msg)
                    data: dict[str, Any] = await resp.json()
        except GoogleMapsApiError:
            raise
        except Exception as err:
            msg = f"Place Details request failed: {err}"
            raise GoogleMapsApiError(msg) from err
        return self._simplify_details(data)

    async def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with (
                async_timeout.timeout(HTTP_TIMEOUT),
                self._session.get(url, params=params) as resp,
            ):
                resp.raise_for_status()
                data: dict[str, Any] = await resp.json()
        except Exception as err:
            msg = f"Request failed: {err}"
            raise GoogleMapsApiError(msg) from err

        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            error_message = data.get("error_message", status)
            msg = f"Google Maps API error: {error_message}"
            raise GoogleMapsApiError(msg)
        return data

    @staticmethod
    def extract_first_location(results: dict[str, Any]) -> dict[str, Any] | None:
        """Return first result simplified (formatted address + lat/lng)."""
        res: list[dict[str, Any]] = results.get("results", [])
        if not res:
            return None
        top = res[0]
        geom = top.get("geometry", {}).get("location", {})
        return {
            "formatted_address": top.get("formatted_address"),
            "lat": geom.get("lat"),
            "lng": geom.get("lng"),
            "place_id": top.get("place_id"),
            "types": top.get("types"),
        }
