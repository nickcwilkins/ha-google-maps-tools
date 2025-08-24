"""
Config & options flow for Google Maps Tools.

Only authentication / required parameters (API key) are handled in the config
flow. Optional behavioral defaults (language, region, travel mode) are managed
via the options flow so they can be changed without re-entering credentials.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_LANGUAGE,
    CONF_DEFAULT_TRAVEL_MODE,
    DEFAULT_LANGUAGE,
    DEFAULT_TRAVEL_MODE,
    DOMAIN,
)


class GoogleMapsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow (API key only) for Google Maps Tools."""

    VERSION = 1

    async def async_step_reconfigure(  # type: ignore[override]
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Reconfigure (update) the API key only; other settings moved to options."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            api_key = user_input.get(CONF_API_KEY)
            if not api_key:
                errors["base"] = "api_key"
            else:
                await self.async_set_unique_id("google_maps_api")
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                new_data = {CONF_API_KEY: api_key}
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=new_data,
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_API_KEY, default=entry.data.get(CONF_API_KEY, "")
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                )
            }
        )

        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    async def async_step_user(  # type: ignore[override]
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input.get(CONF_API_KEY)
            if not api_key:
                errors["base"] = "api_key"
            else:
                await self.async_set_unique_id("google_maps_api")
                self._abort_if_unique_id_configured()
                # Only store api key; defaults belong to options.
                return self.async_create_entry(
                    title="Google Maps",
                    data={CONF_API_KEY: api_key},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    # ---------------------------------------------------------------------
    # Options Flow Support
    # ---------------------------------------------------------------------
    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return GoogleMapsOptionsFlow(config_entry)


class GoogleMapsOptionsFlow(OptionsFlowWithReload):
    """Manage defaults (language, region, travel mode) in options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow handler."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:  # type: ignore[override]
        """Handle the options step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Accept user selections verbatim
            return self.async_create_entry(data=user_input)

        opts = self.config_entry.options
        data = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DEFAULT_LANGUAGE,
                    default=opts.get(
                        CONF_DEFAULT_LANGUAGE,
                        data.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE),
                    ),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Optional(
                    CONF_DEFAULT_TRAVEL_MODE,
                    default=opts.get(
                        CONF_DEFAULT_TRAVEL_MODE,
                        data.get(CONF_DEFAULT_TRAVEL_MODE, DEFAULT_TRAVEL_MODE),
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["driving", "walking", "bicycling", "transit"],
                        multiple=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
