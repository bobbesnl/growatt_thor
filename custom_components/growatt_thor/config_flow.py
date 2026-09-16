from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig
import voluptuous as vol
import logging

from .authorization import (
    AuthorizationPolicy,
    CONF_ALLOW_HA_REMOTE_START,
    CONF_AUTHORIZATION,
    CONF_AUTHORIZED_TAGS,
    CONF_RESTRICT_AUTHORIZATION,
    policy_from_input,
)
from .action_errors import async_require_command_completion
from .const import (
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    DEFAULT_PORT,
    CONF_PORT,
    CONF_LOCATION,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .value_validation import (
    NumericValidationError,
    NumericValidationReason,
    validate_poll_interval,
    validate_tcp_port,
)
from .write_queue import (
    VOLATILE_CONTROL_WRITE_POLICY,
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)


def _port_schema_value(value):
    """Apply the protocol port range in the HA form and direct flow calls."""
    try:
        return validate_tcp_port(value)
    except NumericValidationError as exc:
        raise vol.Invalid("invalid_port") from exc


def _poll_interval_schema_value(value):
    """Reject fractional and non-finite intervals instead of coercing them."""
    try:
        return validate_poll_interval(value, minimum=MIN_POLL_INTERVAL)
    except NumericValidationError as exc:
        raise vol.Invalid("invalid_poll_interval") from exc


def _poll_interval_error(exc: NumericValidationError) -> str:
    """Retain the specific minimum error while naming all other bad values."""
    if exc.reason == NumericValidationReason.OUT_OF_RANGE:
        return "poll_interval_too_low"
    return "invalid_poll_interval"


class GrowattThorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Growatt THOR EV Charger."""

    VERSION = CONFIG_ENTRY_VERSION

    async def async_step_user(self, user_input=None):
        """Handle initial setup."""
        # The 1.7 runtime has one domain-global coordinator and OCPP socket.
        # A second entry would therefore expose duplicate entities that both
        # operate on whichever charger connected last.  Fail explicitly until
        # runtime state is deliberately keyed by config-entry ID.
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors = {}

        if user_input is not None:
            normalized_input = dict(user_input)
            try:
                normalized_input[CONF_PORT] = validate_tcp_port(
                    user_input.get(CONF_PORT, DEFAULT_PORT)
                )
            except NumericValidationError:
                errors[CONF_PORT] = "invalid_port"
            try:
                normalized_input[CONF_POLL_INTERVAL] = validate_poll_interval(
                    user_input.get(
                        CONF_POLL_INTERVAL,
                        DEFAULT_POLL_INTERVAL,
                    ),
                    minimum=MIN_POLL_INTERVAL,
                )
            except NumericValidationError as exc:
                errors[CONF_POLL_INTERVAL] = _poll_interval_error(exc)

            if not errors:
                return self.async_create_entry(
                    title="Growatt THOR EV Charger",
                    data=normalized_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PORT,
                        default=DEFAULT_PORT,
                    ): _port_schema_value,
                    vol.Required(CONF_LOCATION, default=""): str,
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=DEFAULT_POLL_INTERVAL,
                        description={
                            "suggested_value": DEFAULT_POLL_INTERVAL
                        }
                    ): _poll_interval_schema_value,
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
        """Show purpose-based options instead of action checkboxes."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["general", "authorization", "confirm_ap_mode"],
        )

    async def async_step_general(self, user_input=None):
        """Manage local polling and location settings."""
        errors = {}

        if user_input is not None:
            try:
                poll_interval = validate_poll_interval(
                    user_input.get(CONF_POLL_INTERVAL),
                    minimum=MIN_POLL_INTERVAL,
                )
            except NumericValidationError as exc:
                errors[CONF_POLL_INTERVAL] = _poll_interval_error(exc)
            else:
                new_location = user_input.get(CONF_LOCATION, "")
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        **self.config_entry.data,
                        CONF_POLL_INTERVAL: poll_interval,
                        CONF_LOCATION: new_location,
                    }
                )
                # Update coordinator location live
                coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
                if coordinator:
                    coordinator.location = new_location
                runtime_data = self.hass.data.get(DOMAIN, {})
                runtime_data["poll_interval"] = poll_interval
                schedule = runtime_data.get("poll_interval_schedule")
                if schedule is not None:
                    # Wake the active sleep so the new cadence starts from
                    # this options save, without reloading the integration.
                    schedule.update(poll_interval)
                return self.async_create_entry(title="", data={})

        current_poll_interval = self.config_entry.data.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
        )
        current_location = self.config_entry.data.get(CONF_LOCATION, "")

        return self.async_show_form(
            step_id="general",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=current_poll_interval,
                    ): _poll_interval_schema_value,
                    vol.Required(
                        CONF_LOCATION,
                        default=current_location,
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "min_interval": str(MIN_POLL_INTERVAL),
                "current_interval": str(current_poll_interval),
            },
        )

    async def async_step_authorization(self, user_input=None):
        """Change only local policy, without sending charger configuration writes."""
        policy = AuthorizationPolicy.from_config(
            self.config_entry.data.get(CONF_AUTHORIZATION)
        )
        errors = {}
        if user_input is not None:
            try:
                updated = policy_from_input(policy, user_input)
            except ValueError as exc:
                errors["base"] = str(exc)
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_AUTHORIZATION: updated.as_config()},
                )
                coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
                if coordinator:
                    coordinator.authorization.policy = updated
                return self.async_create_entry(title="", data={})

        visible_tags = "\n".join(sorted(policy.id_tags))
        if user_input is not None and isinstance(
            user_input.get(CONF_AUTHORIZED_TAGS), str
        ):
            visible_tags = user_input[CONF_AUTHORIZED_TAGS]

        return self.async_show_form(
            step_id="authorization",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_RESTRICT_AUTHORIZATION,
                    default=(user_input or {}).get(
                        CONF_RESTRICT_AUTHORIZATION, policy.restricted
                    ),
                ): bool,
                vol.Required(
                    CONF_ALLOW_HA_REMOTE_START,
                    default=(user_input or {}).get(
                        CONF_ALLOW_HA_REMOTE_START,
                        policy.allow_ha_remote_start,
                    ),
                ): bool,
                vol.Optional(
                    CONF_AUTHORIZED_TAGS,
                    default=visible_tags,
                ): TextSelector(
                    TextSelectorConfig(multiline=True)
                ),
            }),
            errors=errors,
            description_placeholders={"count": str(len(policy.id_tags))},
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

    async def _activate_ap_mode(self):
        """Activate AP Mode via OCPP DataTransfer."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")

        if not charge_point or not coordinator:
            _LOGGER.error("Cannot enable AP Mode: not connected")
            return

        _LOGGER.info("Activating AP Mode...")

        async def _do_ap(current_charge_point):
            status = await current_charge_point.send_data_transfer(
                vendor_id="Growatt",
                message_id="appconfigmode",
            )
            status_value = status.value if hasattr(status, "value") else str(status)
            _LOGGER.info("AP Mode result: %s", status_value)
            if status_value == "Accepted":
                return ChargerWriteResult.success(status)
            return ChargerWriteResult.failed("charger_rejected", status)

        handle = await coordinator.queue_write(
            _do_ap,
            charge_point,
            command_name="DataTransfer(appconfigmode)",
            requires_connection=True,
            policy=VOLATILE_CONTROL_WRITE_POLICY,
        )
        # The success abort screen is shown only after the charger has
        # acknowledged AP mode, not merely after local enqueueing.
        await async_require_command_completion(handle)
