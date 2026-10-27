"""Status sensor: when the lists were last synced and what changed."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TodoSyncConfigEntry
from .const import DOMAIN
from .manager import TodoSyncManager


async def async_setup_entry(
    hass: HomeAssistant, entry: TodoSyncConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([LastSyncSensor(entry.runtime_data, entry)])


class LastSyncSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "last_sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_should_poll = False

    def __init__(self, manager: TodoSyncManager, entry: TodoSyncConfigEntry) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_last_sync"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._manager.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> datetime | None:
        return self._manager.status.last_sync

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._manager.status
        return {
            "list_a": self._manager.list_a,
            "list_b": self._manager.list_b,
            "open_items_a": s.items_a,
            "open_items_b": s.items_b,
            "last_attempt": s.last_attempt.isoformat() if s.last_attempt else None,
            "last_error": s.last_error,
            "last_changes": s.last_actions,
        }
