from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol
import logging

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    CONF_PORT,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

CHARGER_MODE_OPTIONS = {
    "1": "HA/RFID",
    "2": "RFID Only",
    "3": "Plug & Charge",
}
CHARGER_MODE_REVERSE = {v: k for k, v in CHARGER_MODE_OPTIONS.items()}


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

    def __init__(self):
        self._selected_mode = None

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}

        if user_input is not None:
            if user_input.get("enable_ap_mode"):
                return await self.async_step_confirm_ap_mode()

            selected_mode = user_input.get("charger_mode")
            coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
            current_mode_value = str(coordinator.charger_mode) if coordinator and coordinator.charger_mode else None
            current_mode_label = CHARGER_MODE_OPTIONS.get(current_mode_value)

            if selected_mode and selected_mode != current_mode_label:
                self._selected_mode = selected_mode
                return await self.async_step_confirm_charger_mode()

            poll_interval = user_input.get(CONF_POLL_INTERVAL)
            if poll_interval < MIN_POLL_INTERVAL:
                errors[CONF_POLL_INTERVAL] = "poll_interval_too_low"
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_POLL_INTERVAL: poll_interval}
                )
                return self.async_create_entry(title="", data={})

        current_poll_interval = self.config_entry.data.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
        )

        coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
        current_mode_value = str(coordinator.charger_mode) if coordinator and coordinator.charger_mode else None
        current_mode_label = CHARGER_MODE_OPTIONS.get(current_mode_value, "HA/RFID")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=current_poll_interval,
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL)),
                    vol.Optional(
                        "charger_mode",
                        default=current_mode_label,
                    ): vol.In(list(CHARGER_MODE_REVERSE.keys())),
                    vol.Optional("enable_ap_mode", default=False): bool,
                }
            ),
            errors=errors,
            description_placeholders={
                "min_interval": str(MIN_POLL_INTERVAL),
                "current_interval": str(current_poll_interval),
            },
        )

    async def async_step_confirm_charger_mode(self, user_input=None):
        """Confirm charger mode change - warns about reboot."""
        if user_input is not None:
            if user_input.get("confirm"):
                await self._apply_charger_mode(self._selected_mode)
                return self.async_abort(reason="charger_mode_changed")
            else:
                return await self.async_step_init()

        return self.async_show_form(
            step_id="confirm_charger_mode",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): bool,
                }
            ),
            description_placeholders={
                "selected_mode": self._selected_mode,
            },
        )

    async def async_step_confirm_ap_mode(self, user_input=None):
        """Confirm AP Mode."""
        if user_input is not None:
            if user_input.get("confirm"):
                await self._activate_ap_mode()
                return self.async_abort(reason="ap_mode_activated")
            else:
                return await self.async_step_init()

        return self.async_show_form(
            step_id="confirm_ap_mode",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): bool,
                }
            ),
        )

    async def _apply_charger_mode(self, option: str):
        """Write charger mode to the THOR via OCPP."""
        from ocpp.v16.enums import ConfigurationStatus

        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")

        if not charge_point or not coordinator:
            _LOGGER.error("Cannot change Charger Mode: not connected")
            return

        value = CHARGER_MODE_REVERSE.get(option)
        if not value:
            _LOGGER.error("Invalid charger mode: %s", option)
            return

        _LOGGER.info("Setting G_ChargerMode to %s (%s)", value, option)

        async def _do_mode():
            result = await charge_point.change_configuration("G_ChargerMode", value)
            if result in (ConfigurationStatus.accepted, ConfigurationStatus.reboot_required):
                coordinator.charger_mode = int(value)
                coordinator.async_set_updated_data(True)
                _LOGGER.info("Charger Mode changed to %s (result: %s)", option, result)
            else:
                _LOGGER.error("Charger Mode change rejected: %s", result)

        await coordinator.queue_write(_do_mode)

    async def _activate_ap_mode(self):
        """Activate AP Mode via OCPP DataTransfer."""
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
