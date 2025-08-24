"""Google Maps Tools integration setup."""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from dateutil import parser as dateutil_parser
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.helpers import llm
from homeassistant.helpers.aiohttp_client import async_get_clientsession

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from homeassistant.core import HomeAssistant

from .api import DirectionsOptions, GoogleMapsApiClient
from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_LANGUAGE,
    CONF_DEFAULT_REGION,
    CONF_DEFAULT_TRAVEL_MODE,
    DEFAULT_LANGUAGE,
    DEFAULT_REGION,
    DEFAULT_TRAVEL_MODE,
    DIRECTIONS_ARRIVAL_TIME_DESC,
    DIRECTIONS_DEPARTURE_TIME_DESC,
    DOMAIN,
    LLM_API_ID,
    TOOL_DIRECTIONS,
    TOOL_GEOCODE,
    TOOL_REVERSE_GEOCODE,
)

_LOGGER = logging.getLogger(__name__)
type GoogleMapsConfigEntry = ConfigEntry


def get_location_bias(hass: HomeAssistant) -> str | None:
    """
    Return a small bounding box around zone.home for geocode bias.

    Google Geocoding API supports a 'bounds' parameter formatted as
    southwest_lat,southwest_lng|northeast_lat,northeast_lng which *biases* (not
    restricts) results toward that box. We create a ~0.02 degree box (~2 km)
    around the home location. If home location not available, return None.
    """
    # zone.home entity stores coordinates; fallback to config latitude/longitude.
    latitude = getattr(hass.config, "latitude", None)
    longitude = getattr(hass.config, "longitude", None)
    if latitude is None or longitude is None:
        return None
    delta = 0.01  # ~1.1 km latitude; acceptable small bias
    south = latitude - delta
    north = latitude + delta
    west = longitude - delta
    east = longitude + delta
    return f"{south},{west}|{north},{east}"


@dataclass
class GoogleMapsRuntimeData:
    """
    Runtime data stored on entry.

    We only need to store the API client. The LLM API unregister callback is
    registered via `entry.async_on_unload`, which is the standard Home Assistant
    pattern. Defaults are persisted in the config entry data and should be
    accessed from there instead of introspecting the unregister callback.
    """

    client: GoogleMapsApiClient


async def async_setup_entry(hass: HomeAssistant, entry: GoogleMapsConfigEntry) -> bool:
    """Set up Google Maps Tools from a config entry."""
    session = async_get_clientsession(hass)
    api_key: str = entry.data[CONF_API_KEY]
    client = GoogleMapsApiClient(api_key, session)

    # Register LLM API
    unregister_llm = llm.async_register_api(
        hass,
        GoogleMapsLLMAPI(
            hass=hass,
            api_id=LLM_API_ID,
            name="Google Maps",
            entry_id=entry.entry_id,
            client=client,
        ),
    )
    # Ensure API is unregistered when the config entry unloads.
    entry.async_on_unload(unregister_llm)

    entry.runtime_data = GoogleMapsRuntimeData(client=client)  # type: ignore[attr-defined]
    return True


async def async_unload_entry(
    _hass: HomeAssistant, _entry: GoogleMapsConfigEntry
) -> bool:
    """Unload a config entry."""
    # Nothing extra to do; unregister handled by async_on_unload callback.
    return True


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
        # Read persisted defaults from config entry data with constant fallbacks.
        data = entry.data
        language = tool_input.tool_args.get(
            "language", data.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
        )
        region = tool_input.tool_args.get(
            "region", data.get(CONF_DEFAULT_REGION, DEFAULT_REGION)
        )
        # Optional location bias from zone.home location -> small bounding box
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
        data = entry.data
        language = tool_input.tool_args.get(
            "language", data.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
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
        data = entry.data
        language = tool_input.tool_args.get(
            "language", data.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
        )
        region = tool_input.tool_args.get(
            "region", data.get(CONF_DEFAULT_REGION, DEFAULT_REGION)
        )
        mode = tool_input.tool_args.get(
            "mode", data.get(CONF_DEFAULT_TRAVEL_MODE, DEFAULT_TRAVEL_MODE)
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
        _LOGGER.debug(
            "Requesting directions tool_input=%s",
            tool_input,
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


class GoogleMapsLLMAPI(llm.API):  # type: ignore[misc]
    """LLM API exposing Google Maps tools."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_id: str,
        name: str,
        entry_id: str,
        client: GoogleMapsApiClient,
    ) -> None:
        """Initialize the LLM API wrapper."""
        super().__init__(hass=hass, id=api_id, name=name)
        self.entry_id = entry_id
        self.client = client

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        """Return an API instance with tools for the LLM session."""
        geocode_schema = vol.Schema(
            {
                vol.Optional("address"): cv.string,
                vol.Optional("components"): cv.string,
                vol.Optional("language"): cv.string,
                vol.Optional("region"): cv.string,
            }
        )
        reverse_schema = vol.Schema(
            {
                vol.Required("lat"): vol.Coerce(float),
                vol.Required("lng"): vol.Coerce(float),
                vol.Optional("language"): cv.string,
                vol.Optional("result_type"): cv.string,
                vol.Optional("location_type"): cv.string,
            }
        )
        directions_schema = vol.Schema(
            {
                vol.Required("origin"): cv.string,
                vol.Required("destination"): cv.string,
                vol.Optional("mode"): vol.In(
                    ["driving", "walking", "bicycling", "transit"]
                ),
                vol.Optional("language"): cv.string,
                vol.Optional("region"): cv.string,
                vol.Optional("alternatives"): cv.boolean,
                vol.Optional(
                    "departure_time",
                    description=DIRECTIONS_DEPARTURE_TIME_DESC,
                ): vol.Any(vol.Coerce(int), cv.string),
                vol.Optional(
                    "arrival_time",
                    description=DIRECTIONS_ARRIVAL_TIME_DESC,
                ): vol.Any(vol.Coerce(int), cv.string),
                vol.Optional("avoid"): cv.string,
            }
        )

        tools: list[llm.Tool] = [
            GeocodeTool(
                TOOL_GEOCODE,
                "Geocode an address or component filter",
                geocode_schema,
                self.entry_id,
            ),
            ReverseGeocodeTool(
                TOOL_REVERSE_GEOCODE,
                "Reverse geocode coordinates",
                reverse_schema,
                self.entry_id,
            ),
            DirectionsTool(
                TOOL_DIRECTIONS,
                "Get directions between origin and destination",
                directions_schema,
                self.entry_id,
            ),
        ]
        prompt = (
            "You can use Google Maps tools to find coordinates, addresses, and "
            "directions. The API supports specifying addresses as lat/lng, address,"
            " or natural language."
        )
        return llm.APIInstance(
            api=self, api_prompt=prompt, llm_context=llm_context, tools=tools
        )
