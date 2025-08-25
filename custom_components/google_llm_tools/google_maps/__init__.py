"""Google maps LLM API support."""

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .api import GoogleMapsApiClient
from .const import (
    DIRECTIONS_ARRIVAL_TIME_DESC,
    DIRECTIONS_DEPARTURE_TIME_DESC,
    TOOL_DIRECTIONS,
    TOOL_GEOCODE,
    TOOL_PLACE_DETAILS,
    TOOL_PLACES_SEARCH_NEARBY,
    TOOL_PLACES_SEARCH_TEXT,
    TOOL_REVERSE_GEOCODE,
)
from .tools import (
    NEARBY_SEARCH_SCHEMA,
    PLACE_DETAILS_SCHEMA,
    TEXT_SEARCH_SCHEMA,
    DirectionsTool,
    GeocodeTool,
    PlaceDetailsTool,
    PlacesNearbySearchTool,
    PlacesTextSearchTool,
    ReverseGeocodeTool,
)


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
            PlacesTextSearchTool(
                TOOL_PLACES_SEARCH_TEXT,
                "Search for places with free text query (minimal fields)",
                TEXT_SEARCH_SCHEMA,
                self.entry_id,
            ),
            PlacesNearbySearchTool(
                TOOL_PLACES_SEARCH_NEARBY,
                "Search for places near a location by types",
                NEARBY_SEARCH_SCHEMA,
                self.entry_id,
            ),
            PlaceDetailsTool(
                TOOL_PLACE_DETAILS,
                "Fetch details for a place id (hours, phone, website)",
                PLACE_DETAILS_SCHEMA,
                self.entry_id,
            ),
        ]
        prompt = (
            "You can use Google Maps tools to geocode, reverse geocode, get "
            "directions, search for nearby or matching places, and fetch place "
            "details like hours, phone, and website."
        )
        return llm.APIInstance(
            api=self, api_prompt=prompt, llm_context=llm_context, tools=tools
        )
