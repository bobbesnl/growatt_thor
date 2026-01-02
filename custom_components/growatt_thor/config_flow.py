from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    DEFAULT_HOST,
    CONF_HOST,
    CONF_PORT,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)


class GrowattThorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Growatt THOR EV Charger."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle initial setup."""
        errors = {}

        if user_input is not None:
            # Valideer poll interval
            poll_interval = user_input.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)

            if poll_interval < MIN_POLL_INTERVAL:
                errors[CONF_POLL_INTERVAL] = "poll_interval_too_low"
            else:
                return self.async_create_entry(
                    title="Growatt THOR EV Charger",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=DEFAULT_POLL_INTERVAL,
                        description={
                            "suggested_value": DEFAULT_POLL_INTERVAL
                        }
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL)),
                }
            ),
            errors=errors,
            description_placeholders={
                "min_interval": str(MIN_POLL_INTERVAL),
                "default_interval": str(DEFAULT_POLL_INTERVAL),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return GrowattThorOptionsFlow()


class GrowattThorOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Growatt THOR."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}

        if user_input is not None:
            # Valideer poll interval
            poll_interval = user_input.get(CONF_POLL_INTERVAL)

            if poll_interval < MIN_POLL_INTERVAL:
                errors[CONF_POLL_INTERVAL] = "poll_interval_too_low"
            else:
                # Update config entry data
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, **user_input}
                )
                return self.async_create_entry(title="", data={})

        current_poll_interval = self.config_entry.data.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=current_poll_interval,
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL)),
                }
            ),
            errors=errors,
            description_placeholders={
                "min_interval": str(MIN_POLL_INTERVAL),
                "current_interval": str(current_poll_interval),
            },
        )

