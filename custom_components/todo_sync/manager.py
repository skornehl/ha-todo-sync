"""Glue between the pure merge (sync.py) and Home Assistant's todo entities."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ABSENCE_CONFIRM_SECONDS,
    CONF_LIST_A,
    CONF_LIST_B,
    DEBOUNCE_SECONDS,
    DOMAIN,
    MASS_CHANGE_MIN,
    MASS_CHANGE_SHARE,
    PENDING_GRACE_SECONDS,
    SCAN_INTERVAL_MINUTES,
    STORAGE_VERSION,
)
from .sync import DONE, OPEN, Action, Item, merge

_LOGGER = logging.getLogger(__name__)


class SyncSkipped(Exception):
    """A sync was not attempted (a list is unavailable, or the result looked unsafe)."""


@dataclass
class SyncStatus:
    last_sync: datetime | None = None
    last_attempt: datetime | None = None
    last_error: str | None = None
    last_actions: list[str] = field(default_factory=list)
    items_a: int = 0
    items_b: int = 0


class TodoSyncManager:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.list_a: str = entry.data[CONF_LIST_A]
        self.list_b: str = entry.data[CONF_LIST_B]
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}"
        )
        self._snapshot: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._unsubs: list[CALLBACK_TYPE] = []
        self._listeners: list[Callable[[], None]] = []
        self.status = SyncStatus()
        self._debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=DEBOUNCE_SECONDS,
            immediate=False,
            function=self.async_sync,
        )

    async def async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self._snapshot = stored.get("snapshot", {})
        self._pending = stored.get("pending", {})
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self.list_a, self.list_b], self._handle_state_change
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._handle_interval,
                timedelta(minutes=SCAN_INTERVAL_MINUTES),
                name=f"{DOMAIN} {self.entry.entry_id}",
            )
        )
        await self._debouncer.async_call()

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._debouncer.async_shutdown()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _handle_state_change(self, event: Event) -> None:
        self.hass.async_create_task(self._debouncer.async_call())

    async def _handle_interval(self, _now: datetime) -> None:
        await self._debouncer.async_call()

    async def async_sync(self, force: bool = False) -> None:
        """force skips the mass-change guard (service sync_now with force: true)."""
        async with self._lock:
            self.status.last_attempt = dt_util.utcnow()
            try:
                actions = await self._async_sync_locked(force)
            except SyncSkipped as err:
                self.status.last_error = str(err)
                _LOGGER.warning("Sync %s <-> %s skipped: %s", self.list_a, self.list_b, err)
            except Exception as err:  # noqa: BLE001 - surfaced on the sensor
                self.status.last_error = f"{type(err).__name__}: {err}"
                _LOGGER.exception("Sync %s <-> %s failed", self.list_a, self.list_b)
            else:
                self.status.last_error = None
                self.status.last_sync = self.status.last_attempt
                if actions:
                    self.status.last_actions = actions
            for listener in list(self._listeners):
                listener()

    async def _async_sync_locked(self, force: bool) -> list[str]:
        a_items = await self._async_get_items(self.list_a)
        b_items = await self._async_get_items(self.list_b)
        self.status.items_a = sum(1 for i in a_items if i.status == OPEN)
        self.status.items_b = sum(1 for i in b_items if i.status == OPEN)

        now = dt_util.utcnow().timestamp()
        result = merge(
            a_items,
            b_items,
            self._snapshot,
            self._pending,
            now,
            PENDING_GRACE_SECONDS,
            ABSENCE_CONFIRM_SECONDS,
        )
        if not force:
            self._check_mass_change(result.actions)

        done: list[str] = []
        for action in result.actions:
            await self._async_apply(action)
            done.append(_describe(action, self.list_a, self.list_b))
            _LOGGER.info("todo_sync: %s", done[-1])

        self._snapshot = result.snapshot
        self._pending = result.pending
        await self._store.async_save({"snapshot": self._snapshot, "pending": self._pending})
        return done

    def _check_mass_change(self, actions: list[Action]) -> None:
        """One side suddenly looking empty is far more likely an outage than
        a user clearing the whole list - don't mirror that onto the other side."""
        known = len(self._snapshot)
        losing = sum(
            1
            for a in actions
            if a.op == "remove" or (a.op == "set_status" and a.status == DONE)
        )
        if known and losing >= MASS_CHANGE_MIN and losing > known * MASS_CHANGE_SHARE:
            raise SyncSkipped(
                f"{losing} of {known} items would be removed or checked off at once - "
                "looks like one list is temporarily empty, not syncing. Run the "
                "todo_sync.sync_now service with force: true if this is intended."
            )

    async def _async_get_items(self, entity_id: str) -> list[Item]:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            raise SyncSkipped(f"{entity_id} is not available")
        response = await self.hass.services.async_call(
            "todo",
            "get_items",
            {"status": [OPEN, DONE]},
            target={"entity_id": entity_id},
            blocking=True,
            return_response=True,
        )
        raw = (response or {}).get(entity_id, {}).get("items", [])
        return [
            Item(uid=i.get("uid"), summary=i.get("summary", ""), status=i.get("status", OPEN))
            for i in raw
            if i.get("summary")
        ]

    async def _async_apply(self, action: Action) -> None:
        entity_id = self.list_a if action.side == "a" else self.list_b
        target = {"entity_id": entity_id}
        if action.op == "add":
            await self.hass.services.async_call(
                "todo", "add_item", {"item": action.summary}, target=target, blocking=True
            )
            if action.status == DONE:
                await self.hass.services.async_call(
                    "todo",
                    "update_item",
                    {"item": action.summary, "status": DONE},
                    target=target,
                    blocking=True,
                )
        elif action.op == "set_status":
            await self.hass.services.async_call(
                "todo",
                "update_item",
                {"item": action.uid or action.summary, "status": action.status},
                target=target,
                blocking=True,
            )
        elif action.op == "remove":
            await self.hass.services.async_call(
                "todo",
                "remove_item",
                {"item": [action.uid or action.summary]},
                target=target,
                blocking=True,
            )


def _describe(action: Action, list_a: str, list_b: str) -> str:
    where = list_a if action.side == "a" else list_b
    if action.op == "add":
        return f"{where}: + {action.summary}"
    if action.op == "remove":
        return f"{where}: - {action.summary}"
    mark = "✓" if action.status == DONE else "○"
    return f"{where}: {mark} {action.summary}"
