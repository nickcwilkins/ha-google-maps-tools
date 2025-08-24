"""Constants for Google Maps Tools integration."""

from __future__ import annotations

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "google_llm_tools"

# Config entry keys
CONF_API_KEY = "api_key"
CONF_DEFAULT_LANGUAGE = "default_language"
CONF_DEFAULT_REGION = "default_region"
CONF_DEFAULT_TRAVEL_MODE = "default_travel_mode"

# Defaults (can be overridden per call via tool args)
DEFAULT_LANGUAGE = "en"
DEFAULT_TRAVEL_MODE = "driving"  # driving, walking, bicycling, transit

# LLM API id and tool names
LLM_API_ID = "google_maps"

# Timeouts
HTTP_TIMEOUT = 15

# Error messages
ERR_API_KEY_MISSING = "Google Maps API key missing"
ERR_API_REQUEST = "Google Maps API request failed"
ERR_INVALID_RESPONSE = "Google Maps API invalid response"
