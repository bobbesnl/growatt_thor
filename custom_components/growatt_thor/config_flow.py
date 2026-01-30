from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol
import logging

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

_LOGGER = logging.getLogger(__name__)


class GrowattThorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Growatt THOR EV Charger."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle initial setup."""
        errors = {}

        if user_input is not None:
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
            # STEP 1: Check AP Mode
            if user_input.get("enable_ap_mode"):
                return await self.async_step_confirm_ap_mode()

            # STEP 2: poll interval update
            poll_interval = user_input.get(CONF_POLL_INTERVAL)

            if poll_interval < MIN_POLL_INTERVAL:
                errors[CONF_POLL_INTERVAL] = "poll_interval_too_low"
            else:
                # Update config entry data
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_POLL_INTERVAL: poll_interval}
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
                    vol.Optional("enable_ap_mode", default=False): bool,
                }
            ),
            errors=errors,
            description_placeholders={
                "min_interval": str(MIN_POLL_INTERVAL),
                "current_interval": str(current_poll_interval),
            },
        )

    async def async_step_confirm_ap_mode(self, user_input=None):
        """STEP 3: Confirm AP Mode."""
        if user_input is not None:
            if user_input.get("confirm"):
                # Activate AP Mode
                await self._activate_ap_mode()
                # Close menu with message
                return self.async_abort(reason="ap_mode_activated")
            else:
                # User canceled, back to mainmenu
                return await self.async_step_init()

        return self.async_show_form(
            step_id="confirm_ap_mode",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): bool,
                }
            ),
        )

    async def _activate_ap_mode(self):
        """STEP 4: Activate AP Mode"""
        from ocpp.v16 import call

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")

        if not charge_point or not coordinator:
            _LOGGER.error("Cannot enable AP Mode: not connected")
            return

        _LOGGER.info("Activating AP Mode...")

        async def _do_ap():
            result = await charge_point.call(
                call.DataTransferPayload(
                    vendor_id="Growatt",
                    message_id="appconfigmode"
                )
            )
            _LOGGER.info("AP Mode result: %s", result)

        await coordinator.queue_write(_do_ap)
