"""Google Maps Tools integration setup."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import llm
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .google_maps import GoogleMapsLLMAPI

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .const import (
    CONF_API_KEY,
    LLM_API_ID,
)
from .google_maps.api import GoogleMapsApiClient

_LOGGER = logging.getLogger(__name__)
type GoogleMapsConfigEntry = ConfigEntry


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

    entry.runtime_data = GoogleMapsRuntimeData(client=client)
    return True


async def async_unload_entry(
    _hass: HomeAssistant, _entry: GoogleMapsConfigEntry
) -> bool:
    """Unload a config entry."""
    # Nothing extra to do; unregister handled by async_on_unload callback.
    return True
