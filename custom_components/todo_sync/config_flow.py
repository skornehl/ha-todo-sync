"""Config flow: pick the two lists."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import CONF_LIST_A, CONF_LIST_B, DOMAIN

_TODO = selector.EntitySelector(selector.EntitySelectorConfig(domain="todo"))


class TodoSyncConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            a, b = user_input[CONF_LIST_A], user_input[CONF_LIST_B]
            if a == b:
                errors["base"] = "same_list"
            else:
                await self.async_set_unique_id("|".join(sorted((a, b))))
                self._abort_if_unique_id_configured()
                title = " ↔ ".join(
                    (s.name if (s := self.hass.states.get(e)) else e) for e in (a, b)
                )
                return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema({vol.Required(CONF_LIST_A): _TODO, vol.Required(CONF_LIST_B): _TODO})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
