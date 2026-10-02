"""Serve the bundled dashboard card without modifying Lovelace storage."""
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

STATIC_URL = "/growatt_thor_static"
_REGISTERED = "growatt_thor_frontend_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register once per HA process, including across config-entry reloads."""
    if hass.data.get(_REGISTERED):
        return
    integration = await async_get_integration(hass, "growatt_thor")
    await hass.http.async_register_static_paths([
        StaticPathConfig(STATIC_URL, str(Path(__file__).parents[1] / "frontend"), False)
    ])
    add_extra_js_url(hass, f"{STATIC_URL}/thor-card.js?v={integration.version}")
    hass.data[_REGISTERED] = True
