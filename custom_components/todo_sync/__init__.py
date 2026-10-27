"""To-do List Sync: keeps two Home Assistant to-do lists in step."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, SERVICE_SYNC_NOW
from .manager import TodoSyncManager

PLATFORMS = [Platform.SENSOR]

type TodoSyncConfigEntry = ConfigEntry[TodoSyncManager]

SYNC_NOW_SCHEMA = vol.Schema({vol.Optional("force", default=False): cv.boolean})


async def async_setup_entry(hass: HomeAssistant, entry: TodoSyncConfigEntry) -> bool:
    manager = TodoSyncManager(hass, entry)
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await manager.async_setup()

    if not hass.services.has_service(DOMAIN, SERVICE_SYNC_NOW):

        async def _sync_now(call: ServiceCall) -> None:
            for other in hass.config_entries.async_loaded_entries(DOMAIN):
                await other.runtime_data.async_sync(force=call.data["force"])

        hass.services.async_register(DOMAIN, SERVICE_SYNC_NOW, _sync_now, schema=SYNC_NOW_SCHEMA)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TodoSyncConfigEntry) -> bool:
    await entry.runtime_data.async_shutdown()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not [
        e for e in hass.config_entries.async_loaded_entries(DOMAIN) if e.entry_id != entry.entry_id
    ]:
        hass.services.async_remove(DOMAIN, SERVICE_SYNC_NOW)
    return unloaded
