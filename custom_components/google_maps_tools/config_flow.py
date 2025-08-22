"""Config flow for Google Maps Tools."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_LANGUAGE,
    CONF_DEFAULT_REGION,
    CONF_DEFAULT_TRAVEL_MODE,
    DEFAULT_LANGUAGE,
    DEFAULT_REGION,
    DEFAULT_TRAVEL_MODE,
    DOMAIN,
)


class GoogleMapsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Google Maps Tools."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):  # type: ignore[override]
        errors: dict[str, str] = {}
        if user_input is not None:
            # Basic validation: API key non-empty
            if not user_input.get(CONF_API_KEY):
                errors["base"] = "api_key"
            else:
                await self.async_set_unique_id("google_maps_api")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Google Maps", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Optional(
                    CONF_DEFAULT_LANGUAGE, default=DEFAULT_LANGUAGE
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Optional(
                    CONF_DEFAULT_REGION, default=DEFAULT_REGION or ""
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Optional(
                    CONF_DEFAULT_TRAVEL_MODE, default=DEFAULT_TRAVEL_MODE
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["driving", "walking", "bicycling", "transit"],
                        multiple=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
