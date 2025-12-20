from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, DEFAULT_PORT


class GrowattThorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title="Growatt THOR EV Charger",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema={
                "port": DEFAULT_PORT,
            },
        )

