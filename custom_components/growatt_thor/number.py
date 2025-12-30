"""Number entities for Growatt THOR load balancing."""
from __future__ import annotations

import logging
import asyncio

from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberMode
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import UnitOfPower, UnitOfElectricCurrent

from ocpp.v16.enums import ConfigurationStatus

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR number entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        MaxCurrentNumber(coordinator, entry),
        LoadBalancingLimitNumber(coordinator, entry),
    ])


# ─────────────────────────────
# Base class
# ─────────────────────────────

class BaseConfigNumber(CoordinatorEntity, NumberEntity):
    """Base class for Growatt THOR configuration numbers."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_mode = NumberMode.BOX

    def __init__(self, coordinator, entry, key, device_id_suffix=""):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._device_id_suffix = device_id_suffix
        self.hass = coordinator.hass

    async def async_set_native_value(self, value: float) -> None:
        """Update the configuration on the charger."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")

        if not charge_point:
            _LOGGER.warning("Cannot change %s: charger not connected", self.name)
            return

        try:
            formatted_value = self._format_value(value)

            _LOGGER.info("Setting %s to %s", self._config_key, formatted_value)

            result = await charge_point.change_configuration(
                self._config_key,
                formatted_value
            )

            if result == ConfigurationStatus.accepted:
                # Optimistic update
                if hasattr(self.coordinator, self._property_name):
                    setattr(self.coordinator, self._property_name, self._parse_value(formatted_value))
                    self.coordinator.async_set_updated_data(True)

                _LOGGER.info("✅ %s → %s (immediate UI update)", self.name, formatted_value)
            else:
                _LOGGER.error("❌ %s change rejected: %s", self.name, result)

        except Exception as exc:
            _LOGGER.error("❌ Failed to set %s: %s", self.name, exc, exc_info=True)

    def _format_value(self, value: float) -> str:
        """Format value for OCPP (override in subclass if needed)."""
        return str(int(round(value)))  # ← ALTIJD INTEGER!

    def _parse_value(self, value: str):
        """Parse value from OCPP response."""
        return float(value)


# ─────────────────────────────
# Max Current (EV Charger device) - INTEGERS!
# ─────────────────────────────
class MaxCurrentNumber(BaseConfigNumber):
    """Max current per phase configuration."""

    _attr_name = "Max Current"
    _attr_icon = "mdi:current-ac"
    _attr_native_min_value = 6
    _attr_native_max_value = 32
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "A"
    _config_key = "G_MaxCurrent"
    _property_name = "max_current"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "max_current")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
        self._debounce_task = None  # ← DEBOUNCE TOEGEVOEGD!
        self._pending_value = None  # ← PENDING TOEGEVOEGD!

    @property
    def native_value(self):
        value = self.coordinator.max_current
        return int(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set new value with 5s debounce (net als LoadBalancing!)."""
        value = round(value)  # Integer!

        # Cancel vorige debounce
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        self._pending_value = value
        self._debounce_task = asyncio.create_task(self._debounced_set())

    async def _debounced_set(self):
        """Execute setting after 5s debounce."""
        try:
            await asyncio.sleep(5.0)
            if self._pending_value is not None:
                await super().async_set_native_value(self._pending_value)
                self._pending_value = None
        except asyncio.CancelledError:
            pass

    def _format_value(self, value: float) -> str:
        """Format as XX (integer, Growatt format)."""
        return str(int(round(value)))

# ─────────────────────────────
# Load Balancing Limit (Load balancing device) - INTEGERS!
# ─────────────────────────────

class LoadBalancingLimitNumber(BaseConfigNumber):
    """Load balancing limit (kW) configuration."""

    _attr_name = "Loadbalancing limit"
    _attr_icon = "mdi:speedometer"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_min_value = 1      # ← INTEGER (1-50 kW)
    _attr_native_max_value = 50     # ← INTEGER
    _attr_native_step = 1           # ← INTEGER STEP
    _attr_native_unit_of_measurement = "kW"
    _config_key = "G_ExternalLimitPower"
    _property_name = "external_limit_power"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "load_balancing_limit", "grid_connection")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, "grid_connection")},
            "name": "Growatt THOR Load balancing",
            "manufacturer": "Growatt",
            "model": "THOR Load balancing",
        }
        self._debounce_task = None
        self._pending_value = None

    @property
    def native_value(self):
        """Return current value with debounce awareness."""
        value = getattr(self.coordinator, self._property_name, None)
        return int(value) if value is not None else 10

    async def async_set_native_value(self, value: float) -> None:
        """Set new value with 5s debounce (integers only)."""
        # ✅ Automatisch naar integer door BaseConfigNumber._format_value
        value = round(value)  # Extra zekerheid
        
        # Cancel vorige debounce
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        self._pending_value = value
        self._debounce_task = asyncio.create_task(self._debounced_set())

    async def _debounced_set(self):
        """Execute setting after debounce delay."""
        try:
            await asyncio.sleep(5.0)  # 5 SECONDEN WACHTEN
            if self._pending_value is not None:
                await super().async_set_native_value(self._pending_value)
                self._pending_value = None
        except asyncio.CancelledError:
            pass  # Normaal - nieuwe wijziging annuleerde deze

