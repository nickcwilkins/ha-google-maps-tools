"""Base tool for Google Maps."""

from math import ceil
from typing import Any
from zoneinfo import ZoneInfo

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from dateutil import parser as dateutil_parser
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from ..const import (
    CONF_DEFAULT_LANGUAGE,
    CONF_DEFAULT_TRAVEL_MODE,
    DEFAULT_LANGUAGE,
    DEFAULT_TRAVEL_MODE,
    DOMAIN,
)
from ..util import get_location_bias
from .api import DirectionsOptions, GoogleMapsApiClient


class GoogleMapsTool(llm.Tool):
    """
    Base tool for Google Maps.

    Stores the config entry id so we can fetch the loaded entry directly via
    hass.config_entries.async_get_entry instead of scanning all entries.
    """

    def __init__(
        self, name: str, description: str, schema: vol.Schema, entry_id: str
    ) -> None:
        """
        Initialize a tool.

        name: Tool name exposed to the LLM.
        description: Short description of what the tool does.
        schema: Voluptuous schema describing parameters.
        entry_id: Config entry id for this integration instance.
        """
        self.name = name
        self.description = description
        self.parameters = schema
        self._entry_id = entry_id


class GeocodeTool(GoogleMapsTool):
    """Tool to geocode an address or component filter."""

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        _llm_context: llm.LLMContext,
    ) -> dict[str, Any]:
        """Execute geocode request and return simplified results."""
        entry = _get_entry(hass, self._entry_id)
        client = entry.runtime_data.client  # type: ignore[attr-defined]
        # Defaults now live in entry.options; fall back to legacy data for
        # backward compatibility.
        options = entry.options
        language = tool_input.tool_args.get(
            "language", options.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
        )
        # Default region derived from HA global country setting (hass.data["country"]).
        region = tool_input.tool_args.get("region") or hass.data.get("country")
        bounds = get_location_bias(hass)
        res = await client.geocode(
            address=tool_input.tool_args.get("address"),
            components=tool_input.tool_args.get("components"),
            language=language,
            region=region,
            bounds=bounds,
        )
        simple = client.extract_first_location(res)
        return {
            "status": res.get("status"),
            "result": simple,
            "raw_count": len(res.get("results", [])),
        }


class ReverseGeocodeTool(GoogleMapsTool):
    """Tool to reverse geocode coordinates."""

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        _llm_context: llm.LLMContext,
    ) -> dict[str, Any]:
        """Execute reverse geocode request and return simplified results."""
        entry = _get_entry(hass, self._entry_id)
        client = entry.runtime_data.client  # type: ignore[attr-defined]
        options = entry.options
        language = tool_input.tool_args.get(
            "language", options.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
        )
        return await client.reverse_geocode(
            lat=tool_input.tool_args["lat"],
            lng=tool_input.tool_args["lng"],
            language=language,
            result_type=tool_input.tool_args.get("result_type"),
            location_type=tool_input.tool_args.get("location_type"),
        )


class DirectionsTool(GoogleMapsTool):
    """Tool to fetch directions between two locations."""

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        _llm_context: llm.LLMContext,
    ) -> dict[str, Any]:
        """Execute directions request and return summary."""
        entry = _get_entry(hass, self._entry_id)
        client = entry.runtime_data.client  # type: ignore[attr-defined]
        options = entry.options
        language = tool_input.tool_args.get(
            "language", options.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
        )
        region = tool_input.tool_args.get("region") or hass.data.get("country")
        mode = tool_input.tool_args.get(
            "mode", options.get(CONF_DEFAULT_TRAVEL_MODE, DEFAULT_TRAVEL_MODE)
        )
        origin = tool_input.tool_args["origin"]
        destination = tool_input.tool_args["destination"]

        def _parse_time(value: Any) -> int | None:
            """
            Parse user supplied time (epoch int or natural language) to epoch seconds.

            Accepts:
            - int (epoch seconds)
            - str like "5:00pm", "3:30 pm", "2:30pm Monday, March 29th, 2025".
            Returns epoch seconds or None if unparseable.
            """
            if value in (None, ""):
                return None
            if isinstance(value, int):
                return value
            if isinstance(value, (float,)):
                return int(value)
            if isinstance(value, str):
                try:
                    dt = dateutil_parser.parse(value, fuzzy=True)
                except (ValueError, TypeError):  # pragma: no cover - defensive
                    return None
                # If no timezone info, assume Home Assistant local tz; fallback UTC.
                if dt.tzinfo is None:
                    tzname = getattr(hass.config, "time_zone", None)
                    if tzname:
                        try:
                            dt = dt.replace(tzinfo=ZoneInfo(tzname))
                        except (ValueError, OSError):
                            # pragma: no cover - fallback to UTC
                            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                    else:  # Fallback UTC
                        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                return int(dt.timestamp())
            return None

        departure_time = _parse_time(tool_input.tool_args.get("departure_time"))
        arrival_time = _parse_time(tool_input.tool_args.get("arrival_time"))
        options = DirectionsOptions(
            mode=mode,
            language=language,
            region=region,
            alternatives=tool_input.tool_args.get("alternatives"),
            units=tool_input.tool_args.get("units"),
            departure_time=departure_time,
            arrival_time=arrival_time,
            avoid=tool_input.tool_args.get("avoid"),
        )
        res = await client.directions(origin, destination, options)

        return res.get("routes", [])


_ERR_NO_ENTRY = "Google Maps Tools config entry not loaded or unavailable"


def _get_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry:
    """Return the loaded config entry or raise RuntimeError."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if (
        entry is not None
        and entry.domain == DOMAIN
        and entry.state is ConfigEntryState.LOADED
    ):
        return entry
    raise RuntimeError(_ERR_NO_ENTRY)


PRICE_LEVEL_ALLOWED = ["INEXPENSIVE", "MODERATE", "EXPENSIVE", "VERY_EXPENSIVE"]
MAX_RATING = 5.0


def _round_rating(value: float) -> float:
    return ceil(value * 2.0) / 2.0


def _validate_rating(value: Any) -> float:
    value_f = float(value)
    if value_f < 0 or value_f > MAX_RATING:  # pragma: no cover
        msg = "min_rating must be between 0 and 5"
        raise vol.Invalid(msg)
    return value_f


class PlacesTextSearchTool(GoogleMapsTool):
    """
    LLM tool performing a Places text search.

    Accepts a free-form `text_query` plus optional filters. A bias circle is built
    from provided coordinates or the Home Assistant home location when a radius
    is given.
    """

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        _llm_context: llm.LLMContext,
    ) -> dict[str, Any]:
        """Execute the text search and return simplified place list."""
        entry = _get_entry(hass, self._entry_id)
        client: GoogleMapsApiClient = entry.runtime_data.client  # type: ignore[attr-defined]
        opts = entry.options
        language = tool_input.tool_args.get(
            "language", opts.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
        )
        region = tool_input.tool_args.get("region") or hass.data.get("country")
        radius_m = tool_input.tool_args.get("radius_m")
        lat = tool_input.tool_args.get("lat")
        lng = tool_input.tool_args.get("lng")
        bias_center: tuple[float, float] | None = None
        if radius_m:
            if lat is not None and lng is not None:
                bias_center = (float(lat), float(lng))
            elif hass.config.latitude is not None and hass.config.longitude is not None:
                bias_center = (hass.config.latitude, hass.config.longitude)
        min_rating = tool_input.tool_args.get("min_rating")
        normalized_min_rating: float | None = None
        if min_rating is not None:
            min_rating = _validate_rating(min_rating)
            rounded = _round_rating(min_rating)
            if rounded != min_rating:
                normalized_min_rating = rounded
            min_rating = rounded
        page_size = tool_input.tool_args.get("max_results")
        if page_size:
            page_size = max(1, min(20, int(page_size)))
        options = GoogleMapsApiClient.TextSearchOptions(
            text_query=tool_input.tool_args["text_query"],
            included_type=tool_input.tool_args.get("included_type"),
            strict_type_filtering=tool_input.tool_args.get("strict_type_filtering"),
            open_now=tool_input.tool_args.get("open_now"),
            min_rating=min_rating,
            price_levels=tool_input.tool_args.get("price_levels"),
            radius_m=radius_m,
            bias_center=bias_center,
            language=language,
            region=region,
            page_size=page_size,
        )
        res = await client.places_search_text(options)
        if normalized_min_rating is not None:
            res["normalized_min_rating"] = normalized_min_rating
        return res


class PlacesNearbySearchTool(GoogleMapsTool):
    """LLM tool performing a nearby search constrained to a radius circle."""

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        _llm_context: llm.LLMContext,
    ) -> dict[str, Any]:
        """Execute the nearby search and return simplified place list."""
        entry = _get_entry(hass, self._entry_id)
        client: GoogleMapsApiClient = entry.runtime_data.client  # type: ignore[attr-defined]
        opts = entry.options
        language = tool_input.tool_args.get(
            "language", opts.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
        )
        region = tool_input.tool_args.get("region") or hass.data.get("country")
        lat = tool_input.tool_args.get("lat") or hass.config.latitude
        lng = tool_input.tool_args.get("lng") or hass.config.longitude
        if lat is None or lng is None:
            msg = (
                "Home location unknown; provide lat and lng explicitly for "
                "nearby search"
            )
            raise RuntimeError(msg)
        max_results = tool_input.tool_args.get("max_results")
        if max_results:
            max_results = max(1, min(20, int(max_results)))
        options = GoogleMapsApiClient.NearbySearchOptions(
            radius_m=tool_input.tool_args["radius_m"],
            center=(float(lat), float(lng)),
            included_types=tool_input.tool_args.get("included_types"),
            excluded_types=tool_input.tool_args.get("excluded_types"),
            included_primary_types=tool_input.tool_args.get("included_primary_types"),
            excluded_primary_types=tool_input.tool_args.get("excluded_primary_types"),
            language=language,
            region=region,
            max_results=max_results,
            rank=tool_input.tool_args.get("rank"),
        )
        return await client.places_search_nearby(options)


class PlaceDetailsTool(GoogleMapsTool):
    """LLM tool fetching details for a specific place id."""

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        _llm_context: llm.LLMContext,
    ) -> dict[str, Any]:
        """Fetch and return a simplified details object."""
        entry = _get_entry(hass, self._entry_id)
        client: GoogleMapsApiClient = entry.runtime_data.client  # type: ignore[attr-defined]
        opts = entry.options
        language = tool_input.tool_args.get(
            "language", opts.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
        )
        region = tool_input.tool_args.get("region") or hass.data.get("country")
        return await client.place_details(
            tool_input.tool_args["place_id"], language=language, region=region
        )


TEXT_SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required("text_query"): cv.string,
        vol.Optional("included_type"): cv.string,
        vol.Optional("strict_type_filtering"): cv.boolean,
        vol.Optional("open_now"): cv.boolean,
        vol.Optional("min_rating"): vol.All(vol.Coerce(float), _validate_rating),
        vol.Optional("price_levels"): vol.All(
            [vol.In(PRICE_LEVEL_ALLOWED)],
            vol.Length(min=1, max=len(PRICE_LEVEL_ALLOWED)),
        ),
        vol.Optional("radius_m"): vol.All(vol.Coerce(int), vol.Range(min=1, max=50000)),
        vol.Optional("lat"): vol.Coerce(float),
        vol.Optional("lng"): vol.Coerce(float),
        vol.Optional("language"): cv.string,
        vol.Optional("region"): cv.string,
        vol.Optional("max_results"): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    }
)

NEARBY_SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required("radius_m"): vol.All(vol.Coerce(int), vol.Range(min=1, max=50000)),
        vol.Optional("lat"): vol.Coerce(float),
        vol.Optional("lng"): vol.Coerce(float),
        vol.Optional("included_types"): vol.All([cv.string], vol.Length(max=10)),
        vol.Optional("excluded_types"): vol.All([cv.string], vol.Length(max=10)),
        vol.Optional("included_primary_types"): vol.All([cv.string], vol.Length(max=5)),
        vol.Optional("excluded_primary_types"): vol.All([cv.string], vol.Length(max=5)),
        vol.Optional("rank"): vol.In(["POPULARITY", "DISTANCE"]),
        vol.Optional("language"): cv.string,
        vol.Optional("region"): cv.string,
        vol.Optional("max_results"): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    }
)

PLACE_DETAILS_SCHEMA = vol.Schema(
    {
        vol.Required("place_id"): cv.string,
        vol.Optional("language"): cv.string,
        vol.Optional("region"): cv.string,
    }
)
