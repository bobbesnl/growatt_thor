from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)
import voluptuous as vol
import logging
from math import isfinite

from .charging.authorization import (
    AuthorizationPolicy,
    CONF_ALLOW_HA_REMOTE_START,
    CONF_AUTHORIZATION,
    CONF_AUTHORIZED_TAGS,
    CONF_RESTRICT_AUTHORIZATION,
    policy_from_input,
)
from .runtime.action_errors import async_require_command_completion
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
from .energy.currency import configured_currency, normalized_price_unit
from .energy.sources import (
    BATTERY_POSITIVE_DISCHARGE,
    BATTERY_POWER_SIGNS,
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_POWER_SIGN,
    is_power_sensor,
    power_sensor_options,
    tariff_sensor_options,
    duplicate_source_fields,
)
from .energy.stop_guard import (
    AUTO_STOP_MODES, CONF_AUTO_STOP_MODE, CONF_STOP_THRESHOLD, CONF_STOP_HOLD,
    STOP_THRESHOLD_W, STOP_HOLD_SECONDS,
)
from .energy.accounting_runtime import (
    CONF_FIXED_PRICE, CONF_GRID_ENTITY, CONF_GRID_SIGN, CONF_HOUSE_ENTITY,
    CONF_SITE_PROFILE, CONF_SOLAR_ENTITY, CONF_TARIFF_ENTITY, GRID_SIGNS,
    PROFILES,
)
from .configuration.validation import (
    NumericValidationError,
    NumericValidationReason,
    validate_poll_interval,
    validate_tcp_port,
)
from .runtime.write_queue import (
    VOLATILE_CONTROL_WRITE_POLICY,
    ChargerWriteResult,
)

_LOGGER = logging.getLogger(__name__)


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
                    ): int,
                    vol.Required(CONF_LOCATION, default=""): str,
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=DEFAULT_POLL_INTERVAL,
                        description={
                            "suggested_value": DEFAULT_POLL_INTERVAL
                        }
                    ): int,
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
            menu_options=[
                "general",
                "energy_sources",
                "site_accounting",
                "authorization",
                "confirm_ap_mode",
            ],
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

            if not errors:
                new_location = user_input.get(CONF_LOCATION, "")
                updated_data = {
                    **self.config_entry.data,
                    CONF_POLL_INTERVAL: poll_interval,
                    CONF_LOCATION: new_location,
                }
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=updated_data,
                )
                coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
                if coordinator:
                    coordinator.location = new_location
                    coordinator.external_meter_poll_interval = poll_interval
                    coordinator.async_set_updated_data(True)
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
                    ): int,
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

    async def async_step_energy_sources(self, user_input=None):
        """Configure optional display-only household energy observations."""
        errors = {}
        configured_entity = self.config_entry.data.get(
            CONF_BATTERY_POWER_ENTITY, ""
        )
        configured_sign = self.config_entry.data.get(
            CONF_BATTERY_POWER_SIGN, BATTERY_POSITIVE_DISCHARGE
        )

        if user_input is not None:
            battery_entity = user_input.get(CONF_BATTERY_POWER_ENTITY) or None
            battery_sign = user_input.get(
                CONF_BATTERY_POWER_SIGN,
                BATTERY_POSITIVE_DISCHARGE,
            )
            states = getattr(self.hass, "states", {})
            if battery_entity and not is_power_sensor(
                battery_entity,
                states.get(battery_entity),
            ):
                errors[CONF_BATTERY_POWER_ENTITY] = "invalid_power_sensor"
            if battery_entity and battery_sign not in BATTERY_POWER_SIGNS:
                errors[CONF_BATTERY_POWER_SIGN] = "invalid_battery_power_sign"

            if battery_entity:
                assignments = {
                    CONF_BATTERY_POWER_ENTITY: battery_entity,
                    CONF_SOLAR_ENTITY: self.config_entry.data.get(CONF_SOLAR_ENTITY),
                    CONF_HOUSE_ENTITY: self.config_entry.data.get(CONF_HOUSE_ENTITY),
                    CONF_GRID_ENTITY: self.config_entry.data.get(CONF_GRID_ENTITY)
                    if self.config_entry.data.get("site_grid_source") == "ha_sensor" else None,
                }
                if (self.config_entry.data.get(CONF_SITE_PROFILE, "disabled") != "disabled"
                        and CONF_BATTERY_POWER_ENTITY in duplicate_source_fields(assignments)):
                    errors[CONF_BATTERY_POWER_ENTITY] = "duplicate_power_source"
            elif self.config_entry.data.get(CONF_SITE_PROFILE) in ("pv_battery", "grohome_load_first"):
                errors[CONF_BATTERY_POWER_ENTITY] = "profile_requires_battery"
            elif self.config_entry.data.get(CONF_AUTO_STOP_MODE) in ("battery", "battery_or_grid"):
                errors[CONF_BATTERY_POWER_ENTITY] = "auto_stop_requires_battery"

            if not errors:
                updated_data = dict(self.config_entry.data)
                if battery_entity:
                    updated_data[CONF_BATTERY_POWER_ENTITY] = battery_entity
                    updated_data[CONF_BATTERY_POWER_SIGN] = battery_sign
                else:
                    updated_data.pop(CONF_BATTERY_POWER_ENTITY, None)
                    updated_data.pop(CONF_BATTERY_POWER_SIGN, None)
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=updated_data,
                )
                coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
                if coordinator:
                    coordinator.battery_power_entity = battery_entity
                    coordinator.battery_power_sign = (
                        battery_sign
                        if battery_entity
                        else BATTERY_POSITIVE_DISCHARGE
                    )
                    coordinator.site_accounting_options = dict(updated_data)
                    coordinator.async_set_updated_data(True)
                return self.async_create_entry(title="", data={})

        current_battery_entity = (
            user_input.get(CONF_BATTERY_POWER_ENTITY, "")
            if user_input is not None else configured_entity
        ) or ""
        current_battery_sign = (user_input or {}).get(
            CONF_BATTERY_POWER_SIGN,
            configured_sign,
        )
        excluded = set()
        if self.config_entry.data.get(CONF_SITE_PROFILE, "disabled") != "disabled":
            source_keys = [CONF_SOLAR_ENTITY, CONF_HOUSE_ENTITY]
            if self.config_entry.data.get("site_grid_source") == "ha_sensor":
                source_keys.append(CONF_GRID_ENTITY)
            excluded = {self.config_entry.data.get(key) for key in source_keys} - {None, ""}
        return self.async_show_form(
            step_id="energy_sources",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_BATTERY_POWER_ENTITY,
                        description={"suggested_value": current_battery_entity},
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[option for option in power_sensor_options(
                                getattr(self.hass, "states", {}),
                                current_battery_entity or None,
                                exclude=excluded,
                            ) if option["value"]],
                            mode="dropdown",
                            custom_value=True,
                        )
                    ),
                    vol.Required(
                        CONF_BATTERY_POWER_SIGN,
                        default=current_battery_sign,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=list(BATTERY_POWER_SIGNS),
                            translation_key="battery_power_sign",
                            mode="dropdown",
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_site_accounting(self, user_input=None):
        """Configure read-only site bookkeeping; changes apply to future deltas."""
        current = dict(self.config_entry.data)
        errors = {}
        if user_input is not None:
            states = getattr(self.hass, "states", {})
            profile = user_input.get(CONF_SITE_PROFILE, "disabled")
            if profile not in PROFILES:
                errors[CONF_SITE_PROFILE] = "invalid_site_profile"
            auto_stop_mode = user_input.get(CONF_AUTO_STOP_MODE, "off")
            for key, default, low, high in (
                (CONF_STOP_THRESHOLD, STOP_THRESHOLD_W, 100, 10000),
                (CONF_STOP_HOLD, STOP_HOLD_SECONDS, 30, 1800),
            ):
                value = user_input.get(key, current.get(key, default))
                if not isinstance(value, (int, float)) or not isfinite(value) or not low <= value <= high:
                    errors[key] = "invalid_stop_settings"
            if auto_stop_mode not in AUTO_STOP_MODES:
                errors[CONF_AUTO_STOP_MODE] = "invalid_auto_stop_mode"
            elif auto_stop_mode != "off":
                if profile == "disabled":
                    errors[CONF_AUTO_STOP_MODE] = "auto_stop_requires_profile"
                elif auto_stop_mode in ("battery", "battery_or_grid") and not current.get(CONF_BATTERY_POWER_ENTITY):
                    errors[CONF_AUTO_STOP_MODE] = "auto_stop_requires_battery"
            grid_source = user_input.get("site_grid_source", "none")
            if auto_stop_mode in ("grid", "battery_or_grid") and grid_source == "none":
                errors["site_grid_source"] = "grid_source_required"
            if profile in ("pv", "pv_battery", "grohome_load_first") and grid_source == "none":
                errors["site_grid_source"] = "grid_source_required"
            if grid_source == "ha_sensor" and not user_input.get(CONF_GRID_ENTITY):
                errors[CONF_GRID_ENTITY] = "grid_source_required"
            for key in (CONF_GRID_ENTITY, CONF_SOLAR_ENTITY, CONF_HOUSE_ENTITY):
                entity = user_input.get(key)
                if entity and not is_power_sensor(entity, states.get(entity)):
                    errors[key] = "invalid_power_sensor"
            if user_input.get(CONF_GRID_SIGN) not in GRID_SIGNS:
                errors[CONF_GRID_SIGN] = "invalid_grid_sign"
            tariff_entity = user_input.get(CONF_TARIFF_ENTITY)
            if profile != "disabled" and not tariff_entity and user_input.get(CONF_FIXED_PRICE) is None:
                errors[CONF_FIXED_PRICE] = "tariff_required"
            if tariff_entity:
                state = states.get(tariff_entity)
                unit = getattr(state, "attributes", {}).get("unit_of_measurement") if state else None
                if not tariff_entity.startswith("sensor.") or normalized_price_unit(unit, configured_currency(self.hass)) is None:
                    errors[CONF_TARIFF_ENTITY] = "invalid_tariff_sensor"
            if grid_source not in ("none", "thor_external", "ha_sensor"):
                errors["site_grid_source"] = "invalid_grid_source"
            if profile in ("pv_battery", "grohome_load_first") and not current.get(CONF_BATTERY_POWER_ENTITY):
                errors[CONF_SITE_PROFILE] = "profile_requires_battery"
            if profile != "disabled":
                assignments = {
                    CONF_BATTERY_POWER_ENTITY: current.get(CONF_BATTERY_POWER_ENTITY),
                    CONF_GRID_ENTITY: user_input.get(CONF_GRID_ENTITY) if grid_source == "ha_sensor" else None,
                    CONF_SOLAR_ENTITY: user_input.get(CONF_SOLAR_ENTITY),
                    CONF_HOUSE_ENTITY: user_input.get(CONF_HOUSE_ENTITY),
                }
                for key in duplicate_source_fields(assignments) - {CONF_BATTERY_POWER_ENTITY}:
                    errors[key] = "duplicate_power_source"
            price = user_input.get(CONF_FIXED_PRICE)
            if price is not None:
                try:
                    if not isfinite(float(price)):
                        errors[CONF_FIXED_PRICE] = "invalid_fixed_price"
                except (ValueError, TypeError):
                    errors[CONF_FIXED_PRICE] = "invalid_fixed_price"
            if not errors:
                updated = dict(current)
                keys = (CONF_SITE_PROFILE, CONF_GRID_ENTITY, CONF_GRID_SIGN,
                        CONF_SOLAR_ENTITY, CONF_HOUSE_ENTITY, CONF_TARIFF_ENTITY,
                        CONF_FIXED_PRICE, "site_grid_source", CONF_AUTO_STOP_MODE,
                        CONF_STOP_THRESHOLD, CONF_STOP_HOLD)
                for key in keys:
                    value = user_input.get(key, current.get(key)) if key in (CONF_STOP_THRESHOLD, CONF_STOP_HOLD) else user_input.get(key)
                    if value in (None, ""):
                        updated.pop(key, None)
                    else:
                        updated[key] = value
                self.hass.config_entries.async_update_entry(self.config_entry, data=updated)
                coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
                if coordinator:
                    coordinator.site_accounting_options = dict(updated)
                    coordinator.async_set_updated_data(True)
                    guard = self.hass.data.get(DOMAIN, {}).get("energy_stop_guard")
                    if guard is not None:
                        guard.refresh()
                return self.async_create_entry(title="", data={})

        # Redisplay the submitted draft on validation errors, including cleared fields.
        if user_input is not None:
            for key in (CONF_GRID_ENTITY, CONF_SOLAR_ENTITY, CONF_HOUSE_ENTITY, CONF_TARIFF_ENTITY, CONF_FIXED_PRICE):
                current.pop(key, None)
            current.update(user_input)
        states = getattr(self.hass, "states", {})

        def power_selector(key: str, role: str) -> SelectSelector:
            other_keys = {CONF_BATTERY_POWER_ENTITY, CONF_SOLAR_ENTITY, CONF_HOUSE_ENTITY}
            if current.get("site_grid_source") == "ha_sensor":
                other_keys.add(CONF_GRID_ENTITY)
            excluded = {current.get(other) for other in other_keys - {key}} - {None, ""}
            options = power_sensor_options(states, current.get(key), role=role, exclude=excluded)
            # custom_value enables HA's searchable picker; server validation still
            # rejects unknown entities, incompatible units and conflicting roles.
            return SelectSelector(SelectSelectorConfig(
                options=[item for item in options if item["value"]],
                mode="dropdown", custom_value=True,
            ))

        def source_field(key: str):
            return vol.Optional(key, description={"suggested_value": current.get(key, "")})

        price_key = (
            vol.Optional(CONF_FIXED_PRICE, description={"suggested_value": current[CONF_FIXED_PRICE]})
            if current.get(CONF_FIXED_PRICE) is not None else vol.Optional(CONF_FIXED_PRICE)
        )
        return self.async_show_form(
            step_id="site_accounting",
            data_schema=vol.Schema({
                vol.Required(CONF_SITE_PROFILE, default=current.get(CONF_SITE_PROFILE, "disabled")): SelectSelector(SelectSelectorConfig(options=list(PROFILES), translation_key=CONF_SITE_PROFILE, mode="dropdown")),
                vol.Required(CONF_AUTO_STOP_MODE, default=current.get(CONF_AUTO_STOP_MODE, "off")): SelectSelector(SelectSelectorConfig(options=list(AUTO_STOP_MODES), translation_key=CONF_AUTO_STOP_MODE, mode="dropdown")),
                vol.Required(CONF_STOP_THRESHOLD, default=current.get(CONF_STOP_THRESHOLD, STOP_THRESHOLD_W)): vol.All(vol.Coerce(float), vol.Range(min=100, max=10000)),
                vol.Required(CONF_STOP_HOLD, default=current.get(CONF_STOP_HOLD, STOP_HOLD_SECONDS)): vol.All(vol.Coerce(float), vol.Range(min=30, max=1800)),
                vol.Required("site_grid_source", default=current.get("site_grid_source", "none")): SelectSelector(SelectSelectorConfig(options=["none", "thor_external", "ha_sensor"], translation_key="site_grid_source", mode="dropdown")),
                source_field(CONF_GRID_ENTITY): power_selector(CONF_GRID_ENTITY, "grid"),
                vol.Required(CONF_GRID_SIGN, default=current.get(CONF_GRID_SIGN, "positive_import")): SelectSelector(SelectSelectorConfig(options=list(GRID_SIGNS), translation_key=CONF_GRID_SIGN, mode="dropdown")),
                source_field(CONF_SOLAR_ENTITY): power_selector(CONF_SOLAR_ENTITY, "solar"),
                source_field(CONF_HOUSE_ENTITY): power_selector(CONF_HOUSE_ENTITY, "household"),
                source_field(CONF_TARIFF_ENTITY): SelectSelector(SelectSelectorConfig(
                    options=tariff_sensor_options(states, configured_currency(self.hass), current.get(CONF_TARIFF_ENTITY)),
                    mode="dropdown", custom_value=True,
                )),
                price_key: float,
            }),
            errors=errors,
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
