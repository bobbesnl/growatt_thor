"""Button entities for Growatt THOR configuration."""
from __future__ import annotations

import logging
import asyncio

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_ID_TAG = "12345678"  # Growatt handshake key


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Growatt THOR button entities."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_entities([
        StartChargingButton(coordinator, entry),
        StopChargingButton(coordinator, entry),
    ])


# ─────────────────────────────
# Start Charging Button
# ─────────────────────────────

class StartChargingButton(CoordinatorEntity, ButtonEntity):
    """Button to start a charging session."""

    _attr_has_entity_name = True
    _attr_translation_key = "start_charging"
    _attr_icon = "mdi:play-circle"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_start_charging"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
        self.hass = coordinator.hass

    async def async_press(self) -> None:
        """Start a charging session via queue."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot start charging: charger not connected")
            return

        if self.coordinator.status == "Charging":
            _LOGGER.warning(
                "⚠️ Cannot start charging: session already active (transaction_id=%s)",
                self.coordinator.transaction_id
            )
            return

        _LOGGER.info("🔘 Queueing start charging command")
        await self.coordinator.queue_write(self._start_charging, charge_point)

    async def _start_charging(self, charge_point):
        """Start charging command (runs inside write-queue)."""
        try:
            result = await charge_point.remote_start_transaction(
                connector_id=1,
                id_tag=DEFAULT_ID_TAG
            )

            if result.get("status") == "Accepted":
                _LOGGER.info("✅ Charging session started successfully")
                self.hass.async_create_task(self._post_status_update(charge_point))
                self.coordinator.async_set_updated_data(True)
            else:
                _LOGGER.error("❌ Start charging rejected: %s", result.get("status"))

        except Exception as exc:
            _LOGGER.error("❌ Failed to start charging: %s", exc, exc_info=True)

    async def _post_status_update(self, charge_point):
        """Trigger a status update after a short delay (outside write-queue)."""
        await asyncio.sleep(2)
        try:
            await charge_point.trigger_status()
            self.coordinator.async_set_updated_data(True)
        except Exception as exc:
            _LOGGER.error("❌ Failed to trigger status after start: %s", exc, exc_info=True)


# ─────────────────────────────
# Stop Charging Button
# ─────────────────────────────

class StopChargingButton(CoordinatorEntity, ButtonEntity):
    """Button to stop a charging session."""

    _attr_has_entity_name = True
    _attr_translation_key = "stop_charging"
    _attr_icon = "mdi:stop-circle"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_stop_charging"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Growatt THOR EV Charger",
            "manufacturer": "Growatt",
            "model": "THOR",
        }
        self.hass = coordinator.hass

    async def async_press(self) -> None:
        """Stop a charging session via queue."""
        charge_point = self.hass.data.get(DOMAIN, {}).get("charge_point")
        if not charge_point:
            _LOGGER.warning("Cannot stop charging: charger not connected")
            return

        is_charging = self.coordinator.status == "Charging"
        transaction_id = self.coordinator.transaction_id

        if not is_charging and transaction_id is None:
            _LOGGER.warning(
                "⚠️ Cannot stop charging: no active session (status=%s)",
                self.coordinator.status
            )
            return

        # Gebruik transaction_id 0 als fallback (stop huidige sessie)
        tid = transaction_id if transaction_id is not None else 0

        if transaction_id is None:
            _LOGGER.info(
                "🔘 Queueing stop charging (using fallback transaction_id=0, status=%s)",
                self.coordinator.status
            )
        else:
            _LOGGER.info("🔘 Queueing stop charging command (transaction_id=%s)", tid)

        await self.coordinator.queue_write(self._stop_charging, charge_point, tid)

    async def _stop_charging(self, charge_point, transaction_id: int):
        """Stop charging command (runs inside write-queue)."""
        try:
            result = await charge_point.remote_stop_transaction(
                transaction_id=transaction_id
            )

            if result.get("status") == "Accepted":
                _LOGGER.info("✅ Charging session stopped successfully")
                self.hass.async_create_task(self._post_status_update(charge_point))
                self.coordinator.async_set_updated_data(True)
            else:
                _LOGGER.error("❌ Stop charging rejected: %s", result.get("status"))

        except Exception as exc:
            _LOGGER.error("❌ Failed to stop charging: %s", exc, exc_info=True)

    async def _post_status_update(self, charge_point):
        """Trigger a status update after a short delay (outside write-queue)."""
        await asyncio.sleep(2)
        try:
            await charge_point.trigger_status()
            self.coordinator.async_set_updated_data(True)
        except Exception as exc:
            _LOGGER.error("❌ Failed to trigger status after stop: %s", exc, exc_info=True)
