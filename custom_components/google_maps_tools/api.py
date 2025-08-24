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
from typing import Any

import aiohttp
import async_timeout

from .const import (
    GEOCODE_ENDPOINT,
    HTTP_TIMEOUT,
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

    async def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with (
                async_timeout.timeout(HTTP_TIMEOUT),
                self._session.get(url, params=params) as resp,
            ):
                if resp.status in (401, 403):
                    msg = "Authentication error with Google Maps API"
                    raise GoogleMapsAuthError(msg)
                resp.raise_for_status()
                data: dict[str, Any] = await resp.json()
        except Exception as err:  # pylint: disable=broad-except
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
