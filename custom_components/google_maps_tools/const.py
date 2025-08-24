"""Constants for Google Maps Tools integration."""

from __future__ import annotations

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "google_maps_tools"

# Config entry keys
CONF_API_KEY = "api_key"
CONF_DEFAULT_LANGUAGE = "default_language"
CONF_DEFAULT_REGION = "default_region"
CONF_DEFAULT_TRAVEL_MODE = "default_travel_mode"

# Defaults (can be overridden per call via tool args)
DEFAULT_LANGUAGE = "en"
DEFAULT_REGION = None  # e.g. 'us'
DEFAULT_TRAVEL_MODE = "driving"  # driving, walking, bicycling, transit

# API endpoints
GEOCODE_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
# Legacy Directions endpoint (no longer used; retained for reference)
DIRECTIONS_ENDPOINT = "https://maps.googleapis.com/maps/api/directions/json"

# New Routes API endpoint (v2)
ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"

# LLM API id and tool names
LLM_API_ID = "google_maps"
TOOL_GEOCODE = "gmaps_geocode"
TOOL_REVERSE_GEOCODE = "gmaps_reverse_geocode"
TOOL_DIRECTIONS = "gmaps_directions"

# Timeouts
HTTP_TIMEOUT = 15

# Attribution
ATTRIBUTION = "Data provided by Google Maps Platform"

# Error messages
ERR_API_KEY_MISSING = "Google Maps API key missing"
ERR_API_REQUEST = "Google Maps API request failed"
ERR_INVALID_RESPONSE = "Google Maps API invalid response"

DIRECTIONS_DEPARTURE_TIME_DESC = (
    "The time to depart. Accepts date time strings like '5:00pm', "
    "'3:30pm', or full date times like '2:30pm Monday, March 29th, 2025'. "
    "Mutually exclusive with arrival_time"
)

DIRECTIONS_ARRIVAL_TIME_DESC = (
    "The desired arrival time. Accepts date time strings like '5:00pm', "
    "'3:30pm tomorrow', or full date times like '2:30pm Monday, March 29th, 2025'. "
    "Mutually exclusive with departure_time"
)
