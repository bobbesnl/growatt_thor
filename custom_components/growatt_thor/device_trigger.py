"""Device triggers for the charger device, backed by the automation events.

Each trigger listens for one event type with the charger's ``device_id``. The
event data reaches the automation as ``trigger.event.data``; the payloads are
described in ``runtime/automation_events.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .runtime.automation_events import DEVICE_TRIGGER_EVENTS

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, HomeAssistant
    from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
    from homeassistant.helpers.typing import ConfigType

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(list(DEVICE_TRIGGER_EVENTS))}
)


def _is_charger_device(hass: HomeAssistant, device_id: str) -> bool:
    """The external meter device shares the domain but has no own events."""
    device = dr.async_get(hass).async_get(device_id)
    return device is not None and any(
        len(identifier) == 2 and identifier[0] == DOMAIN for identifier in device.identifiers
    )


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    if not _is_charger_device(hass, device_id):
        return []
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: trigger_type,
        }
        for trigger_type in DEVICE_TRIGGER_EVENTS
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: DEVICE_TRIGGER_EVENTS[config[CONF_TYPE]],
            event_trigger.CONF_EVENT_DATA: {CONF_DEVICE_ID: config[CONF_DEVICE_ID]},
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
