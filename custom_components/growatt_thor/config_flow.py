import logging
from html import escape

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .charging.authorization import (
    CONF_ALLOW_HA_REMOTE_START,
    CONF_AUTHORIZATION,
    CONF_AUTHORIZED_TAGS,
    CONF_RESTRICT_AUTHORIZATION,
    AuthorizationPolicy,
    policy_from_input,
)
from .coerce import enum_value
from .configuration.validation import (
    NumericValidationError,
    NumericValidationReason,
    validate_bind_address,
    validate_poll_interval,
    validate_tcp_port,
)
from .const import (
    CONF_BIND_ADDRESS,
    CONF_LOCATION,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_SITE_GRID_SOURCE,
    CONFIG_ENTRY_VERSION,
    DEFAULT_BIND_ADDRESS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
    MIN_POLL_INTERVAL,
)
from .energy.currency import configured_currency
from .energy.options import (
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_POWER_SIGN,
    CONF_FIXED_PRICE,
    CONF_GRID_ENTITY,
    CONF_GRID_SIGN,
    CONF_HOUSE_ENTITY,
    CONF_SITE_PROFILE,
    CONF_SOLAR_ENTITY,
    CONF_TARIFF_ENTITY,
    SITE_GRID_SOURCES,
)
from .energy.site_inputs import GRID_SIGNS, AccountingProfile
from .energy.site_options import profile_requires_battery, validate_site_options
from .energy.sources import (
    BATTERY_POSITIVE_DISCHARGE,
    BATTERY_POWER_SIGNS,
    duplicate_source_fields,
    is_power_sensor,
)
from .energy.stop_guard_policy import (
    AUTO_STOP_MODES,
    CONF_AUTO_STOP_MODE,
    CONF_STOP_HOLD,
    CONF_STOP_THRESHOLD,
    STOP_HOLD_RANGE,
    STOP_HOLD_SECONDS,
    STOP_THRESHOLD_RANGE,
    STOP_THRESHOLD_W,
)
from .runtime.action_errors import async_require_command_completion
from .runtime.keys import ACTIVE_CHARGE_POINT, COORDINATOR, POLL_INTERVAL, POLL_INTERVAL_SCHEDULE
from .runtime.ownership import entry_runtime_data
from .runtime.write_results import (
    VOLATILE_CONTROL_WRITE_POLICY,
    ChargerWriteResult,
)
from .source_discovery import power_sensor_options, tariff_sensor_options

_LOGGER = logging.getLogger(__name__)


def _poll_interval_error(exc: NumericValidationError) -> str:
    """Retain the specific minimum error while naming all other bad values."""
    if exc.reason == NumericValidationReason.OUT_OF_RANGE:
        return "poll_interval_too_low"
    return "invalid_poll_interval"


def build_site_accounting_schema(current, states, currency) -> vol.Schema:
    def power_selector(key: str, role: str) -> SelectSelector:
        other_keys = {
            CONF_BATTERY_POWER_ENTITY,
            CONF_SOLAR_ENTITY,
            CONF_HOUSE_ENTITY,
        }
        if current.get(CONF_SITE_GRID_SOURCE) == "ha_sensor":
            other_keys.add(CONF_GRID_ENTITY)
        excluded = {current.get(other) for other in other_keys - {key}} - {None, ""}
        options = power_sensor_options(states, current.get(key), role=role, exclude=excluded)
        # custom_value enables HA's searchable picker; server validation still
        # rejects unknown entities, incompatible units and conflicting roles.
        return SelectSelector(
            SelectSelectorConfig(
                options=[item for item in options if item["value"]],
                mode="dropdown",
                custom_value=True,
            )
        )

    def source_field(key: str):
        return vol.Optional(key, description={"suggested_value": current.get(key, "")})

    price_key = (
        vol.Optional(
            CONF_FIXED_PRICE,
            description={"suggested_value": current[CONF_FIXED_PRICE]},
        )
        if current.get(CONF_FIXED_PRICE) is not None
        else vol.Optional(CONF_FIXED_PRICE)
    )
    return vol.Schema(
        {
            vol.Required(
                CONF_SITE_PROFILE,
                default=current.get(CONF_SITE_PROFILE, "disabled"),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(AccountingProfile),
                    translation_key=CONF_SITE_PROFILE,
                    mode="dropdown",
                )
            ),
            vol.Required(
                CONF_AUTO_STOP_MODE,
                default=current.get(CONF_AUTO_STOP_MODE, "off"),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(AUTO_STOP_MODES),
                    translation_key=CONF_AUTO_STOP_MODE,
                    mode="dropdown",
                )
            ),
            vol.Required(
                CONF_STOP_THRESHOLD,
                default=current.get(CONF_STOP_THRESHOLD, STOP_THRESHOLD_W),
            ): vol.All(
                vol.Coerce(float),
                vol.Range(min=STOP_THRESHOLD_RANGE[0], max=STOP_THRESHOLD_RANGE[1]),
            ),
            vol.Required(
                CONF_STOP_HOLD,
                default=current.get(CONF_STOP_HOLD, STOP_HOLD_SECONDS),
            ): vol.All(
                vol.Coerce(float), vol.Range(min=STOP_HOLD_RANGE[0], max=STOP_HOLD_RANGE[1])
            ),
            vol.Required(
                CONF_SITE_GRID_SOURCE,
                default=current.get(CONF_SITE_GRID_SOURCE, "none"),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(SITE_GRID_SOURCES),
                    translation_key=CONF_SITE_GRID_SOURCE,
                    mode="dropdown",
                )
            ),
            source_field(CONF_GRID_ENTITY): power_selector(CONF_GRID_ENTITY, "grid"),
            vol.Required(
                CONF_GRID_SIGN,
                default=current.get(CONF_GRID_SIGN, "positive_import"),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(GRID_SIGNS),
                    translation_key=CONF_GRID_SIGN,
                    mode="dropdown",
                )
            ),
            source_field(CONF_SOLAR_ENTITY): power_selector(CONF_SOLAR_ENTITY, "solar"),
            source_field(CONF_HOUSE_ENTITY): power_selector(CONF_HOUSE_ENTITY, "household"),
            source_field(CONF_TARIFF_ENTITY): SelectSelector(
                SelectSelectorConfig(
                    options=tariff_sensor_options(
                        states,
                        currency,
                        current.get(CONF_TARIFF_ENTITY),
                    ),
                    mode="dropdown",
                    custom_value=True,
                )
            ),
            price_key: float,
        }
    )


class GrowattThorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Growatt THOR EV Charger."""

    VERSION = CONFIG_ENTRY_VERSION

    async def async_step_user(self, user_input=None):
        """Handle initial setup."""
        # Every config entry has its own runtime, OCPP server and charger
        # (see runtime_ownership), so a second charger is a second entry.
        # Each entry's server listens on its own port, and the port decides
        # which entry a THOR connects to, so two entries cannot share one.
        errors = {}

        if user_input is not None:
            normalized_input = dict(user_input)
            try:
                normalized_input[CONF_BIND_ADDRESS] = validate_bind_address(
                    user_input.get(CONF_BIND_ADDRESS, DEFAULT_BIND_ADDRESS)
                )
            except ValueError:
                errors[CONF_BIND_ADDRESS] = "invalid_bind_address"
            try:
                normalized_input[CONF_PORT] = validate_tcp_port(
                    user_input.get(CONF_PORT, DEFAULT_PORT)
                )
            except NumericValidationError:
                errors[CONF_PORT] = "invalid_port"
            else:
                if normalized_input[CONF_PORT] in self._configured_ports():
                    errors[CONF_PORT] = "port_already_configured"
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
                title = "Growatt THOR EV Charger"
                if self._async_current_entries():
                    # Keep additional chargers distinguishable in the UI
                    # until the user gives them a name of their own.
                    title = f"{title} (port {normalized_input[CONF_PORT]})"
                return self.async_create_entry(
                    title=title,
                    data=normalized_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PORT,
                        default=DEFAULT_PORT,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=65535,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(CONF_BIND_ADDRESS, default=DEFAULT_BIND_ADDRESS): str,
                    vol.Required(CONF_LOCATION, default=""): str,
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=DEFAULT_POLL_INTERVAL,
                        description={"suggested_value": DEFAULT_POLL_INTERVAL},
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_POLL_INTERVAL,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "min_interval": str(MIN_POLL_INTERVAL),
                "default_interval": str(DEFAULT_POLL_INTERVAL),
            },
        )

    def _configured_ports(self) -> set[int]:
        """Return the OCPP ports already used by existing config entries."""
        ports = set()
        for existing in self._async_current_entries():
            try:
                ports.add(
                    validate_tcp_port(getattr(existing, "data", {}).get(CONF_PORT, DEFAULT_PORT))
                )
            except NumericValidationError:
                # An unusable stored port cannot conflict; its own setup
                # already rejects it.
                continue
        return ports

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return GrowattThorOptionsFlow()


class GrowattThorOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Growatt THOR."""

    def _entry_runtime_data(self):
        """Return the runtime of the entry being configured, if it is loaded."""
        return entry_runtime_data(
            self.hass.data.get(DOMAIN, {}),
            self.config_entry.entry_id,
        )

    def _entry_coordinator(self):
        return (self._entry_runtime_data() or {}).get(COORDINATOR)

    async def async_step_init(self, user_input=None):
        """Show purpose-based options instead of action checkboxes."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "general",
                "energy_sources",
                "site_accounting",
                "authorization",
                "learn_rfid",
                "confirm_ap_mode",
            ],
        )

    async def async_step_general(self, user_input=None):
        """Manage local polling and location settings."""
        errors = {}

        if user_input is not None:
            old_bind = self.config_entry.data.get(CONF_BIND_ADDRESS, DEFAULT_BIND_ADDRESS)
            try:
                bind_address = validate_bind_address(user_input.get(CONF_BIND_ADDRESS, old_bind))
            except ValueError:
                errors[CONF_BIND_ADDRESS] = "invalid_bind_address"
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
                    CONF_BIND_ADDRESS: bind_address,
                }
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=updated_data,
                )
                # Update this entry's running coordinator and poll loop live.
                # Without a loaded runtime the saved entry data is enough.
                runtime_data = self._entry_runtime_data() or {}
                coordinator = runtime_data.get(COORDINATOR)
                if coordinator:
                    await coordinator.async_apply_options(updated_data, section="general")
                if runtime_data:
                    runtime_data[POLL_INTERVAL] = poll_interval
                schedule = runtime_data.get(POLL_INTERVAL_SCHEDULE)
                if schedule is not None:
                    # Wake the active sleep so the new cadence starts from
                    # this options save, without reloading the integration.
                    schedule.update(poll_interval)
                if bind_address != old_bind:
                    await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        current_poll_interval = self.config_entry.data.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
        )
        current_location = self.config_entry.data.get(CONF_LOCATION, "")
        return self.async_show_form(
            step_id="general",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_BIND_ADDRESS,
                        default=self.config_entry.data.get(CONF_BIND_ADDRESS, DEFAULT_BIND_ADDRESS),
                    ): str,
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=current_poll_interval,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_POLL_INTERVAL,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
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
        configured_entity = self.config_entry.data.get(CONF_BATTERY_POWER_ENTITY, "")
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
                    if self.config_entry.data.get(CONF_SITE_GRID_SOURCE) == "ha_sensor"
                    else None,
                }
                if self.config_entry.data.get(
                    CONF_SITE_PROFILE, "disabled"
                ) != "disabled" and CONF_BATTERY_POWER_ENTITY in duplicate_source_fields(
                    assignments
                ):
                    errors[CONF_BATTERY_POWER_ENTITY] = "duplicate_power_source"
            elif profile_requires_battery(self.config_entry.data.get(CONF_SITE_PROFILE)):
                errors[CONF_BATTERY_POWER_ENTITY] = "profile_requires_battery"
            elif self.config_entry.data.get(CONF_AUTO_STOP_MODE) in (
                "battery",
                "battery_or_grid",
            ):
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
                coordinator = self._entry_coordinator()
                if coordinator:
                    await coordinator.async_apply_options(updated_data, section="energy_sources")
                return self.async_create_entry(title="", data={})

        current_battery_entity = (
            user_input.get(CONF_BATTERY_POWER_ENTITY, "")
            if user_input is not None
            else configured_entity
        ) or ""
        current_battery_sign = (user_input or {}).get(
            CONF_BATTERY_POWER_SIGN,
            configured_sign,
        )
        excluded = set()
        if self.config_entry.data.get(CONF_SITE_PROFILE, "disabled") != "disabled":
            source_keys = [CONF_SOLAR_ENTITY, CONF_HOUSE_ENTITY]
            if self.config_entry.data.get(CONF_SITE_GRID_SOURCE) == "ha_sensor":
                source_keys.append(CONF_GRID_ENTITY)
            excluded = {self.config_entry.data.get(key) for key in source_keys} - {
                None,
                "",
            }
        return self.async_show_form(
            step_id="energy_sources",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_BATTERY_POWER_ENTITY,
                        description={"suggested_value": current_battery_entity},
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                option
                                for option in power_sensor_options(
                                    getattr(self.hass, "states", {}),
                                    current_battery_entity or None,
                                    exclude=excluded,
                                )
                                if option["value"]
                            ],
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
            errors = validate_site_options(
                user_input,
                current,
                getattr(self.hass, "states", {}),
                currency=configured_currency(self.hass),
            )
            if not errors:
                updated = dict(current)
                keys = (
                    CONF_SITE_PROFILE,
                    CONF_GRID_ENTITY,
                    CONF_GRID_SIGN,
                    CONF_SOLAR_ENTITY,
                    CONF_HOUSE_ENTITY,
                    CONF_TARIFF_ENTITY,
                    CONF_FIXED_PRICE,
                    CONF_SITE_GRID_SOURCE,
                    CONF_AUTO_STOP_MODE,
                    CONF_STOP_THRESHOLD,
                    CONF_STOP_HOLD,
                )
                for key in keys:
                    value = (
                        user_input.get(key, current.get(key))
                        if key in (CONF_STOP_THRESHOLD, CONF_STOP_HOLD)
                        else user_input.get(key)
                    )
                    if value in (None, ""):
                        updated.pop(key, None)
                    else:
                        updated[key] = value
                self.hass.config_entries.async_update_entry(self.config_entry, data=updated)
                coordinator = self._entry_coordinator()
                if coordinator:
                    await coordinator.async_apply_options(updated, section="site_accounting")
                return self.async_create_entry(title="", data={})

        # Redisplay the submitted draft on validation errors, including cleared fields.
        if user_input is not None:
            for key in (
                CONF_GRID_ENTITY,
                CONF_SOLAR_ENTITY,
                CONF_HOUSE_ENTITY,
                CONF_TARIFF_ENTITY,
                CONF_FIXED_PRICE,
            ):
                current.pop(key, None)
            current.update(user_input)
        states = getattr(self.hass, "states", {})

        return self.async_show_form(
            step_id="site_accounting",
            data_schema=build_site_accounting_schema(
                current, states, configured_currency(self.hass)
            ),
            errors=errors,
        )

    async def async_step_authorization(self, user_input=None):
        """Change only local policy, without sending charger configuration writes."""
        policy = AuthorizationPolicy.from_config(self.config_entry.data.get(CONF_AUTHORIZATION))
        errors = {}
        if user_input is not None:
            try:
                updated = policy_from_input(policy, user_input)
            except ValueError as exc:
                errors["base"] = str(exc)
            else:
                self._save_authorization_policy(updated)
                return self.async_create_entry(title="", data={})

        visible_tags = policy.editable_tags()
        if user_input is not None and isinstance(user_input.get(CONF_AUTHORIZED_TAGS), str):
            visible_tags = user_input[CONF_AUTHORIZED_TAGS]

        return self.async_show_form(
            step_id="authorization",
            data_schema=vol.Schema(
                {
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
                    ): TextSelector(TextSelectorConfig(multiline=True)),
                }
            ),
            errors=errors,
            description_placeholders={"count": str(len(policy.id_tags))},
        )

    def _save_authorization_policy(self, policy):
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, CONF_AUTHORIZATION: policy.as_config()},
        )
        coordinator = self._entry_coordinator()
        if coordinator:
            coordinator.authorization.policy = policy

    def _learning_identifier(self):
        coordinator = self._entry_coordinator()
        learning = getattr(self, "_rfid_learning", None)
        session = getattr(self, "_rfid_session", None)
        if (
            coordinator is None
            or not coordinator.connected
            or learning is not coordinator.authorization.learning
        ):
            if learning is not None and session is not None:
                learning.cancel(session)
            raise ValueError("rfid_charger_unavailable")
        if session is None:
            raise ValueError("rfid_learning_expired")
        return learning.identifier(session)

    async def async_step_learn_rfid(self, user_input=None):
        """Capture only the next Authorize request on this entry's connection."""
        errors = {}
        if getattr(self, "_rfid_session", None) is None:
            coordinator = self._entry_coordinator()
            if coordinator is None or not coordinator.connected:
                return self.async_abort(reason="rfid_charger_unavailable")
            self._rfid_learning = coordinator.authorization.learning
            try:
                self._rfid_session = self._rfid_learning.begin()
            except ValueError as exc:
                return self.async_abort(reason=str(exc))
        try:
            tag = self._learning_identifier()
        except ValueError as exc:
            return self.async_abort(reason=str(exc))
        if user_input is not None:
            if tag is not None:
                return await self.async_step_confirm_rfid()
            errors["base"] = "rfid_not_seen"
        return self.async_show_form(
            step_id="learn_rfid",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_confirm_rfid(self, user_input=None):
        """Add the captured identifier only after the user saves its name."""
        try:
            tag = self._learning_identifier()
        except ValueError as exc:
            return self.async_abort(reason=str(exc))
        if tag is None:
            return await self.async_step_learn_rfid()
        policy = AuthorizationPolicy.from_config(self.config_entry.data.get(CONF_AUTHORIZATION))
        errors = {}
        alias = (user_input or {}).get("alias", policy.aliases.get(tag, ""))
        if user_input is not None:
            try:
                updated = policy.with_card(tag, alias)
            except ValueError as exc:
                errors["base"] = str(exc)
            else:
                self._save_authorization_policy(updated)
                self._rfid_learning.cancel(self._rfid_session)
                return self.async_create_entry(title="", data={})
        # Identifiers are exact wire values, but the description is Markdown.
        display_tag = escape(tag, quote=False).translate(
            str.maketrans({char: "\\" + char for char in "\\`*_{}[]()#+-.!|>"})
        )
        return self.async_show_form(
            step_id="confirm_rfid",
            data_schema=vol.Schema({vol.Optional("alias", default=alias): str}),
            errors=errors,
            description_placeholders={"id_tag": display_tag},
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
        runtime_data = self._entry_runtime_data() or {}
        charge_point = runtime_data.get(ACTIVE_CHARGE_POINT)
        coordinator = runtime_data.get(COORDINATOR)

        if not charge_point or not coordinator:
            _LOGGER.error("Cannot enable AP Mode: not connected")
            return

        _LOGGER.info("Activating AP Mode...")

        async def _do_ap(current_charge_point):
            status = await current_charge_point.send_data_transfer(
                vendor_id="Growatt",
                message_id="appconfigmode",
            )
            status_value = enum_value(status, stringify_fallback=True)
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
