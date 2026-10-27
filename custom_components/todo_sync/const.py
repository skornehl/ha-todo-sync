"""Constants for To-do List Sync."""
from __future__ import annotations

DOMAIN = "todo_sync"

CONF_LIST_A = "list_a"
CONF_LIST_B = "list_b"

# Coalesces the burst of state changes a single edit causes (the Alexa
# shopping list integration rewrites the whole list after each change).
DEBOUNCE_SECONDS = 10
# Safety net next to the state-change trigger.
SCAN_INTERVAL_MINUTES = 5
# How long a write of ours may take to show up on a side before the side's
# own value counts again (Google Keep Sync polls every 15 minutes by default).
PENDING_GRACE_SECONDS = 20 * 60
# Refuse a sync that would take away more than this share of the items
# (and at least MASS_CHANGE_MIN of them) because one side suddenly looks
# empty - a login or API hiccup must not wipe the other list.
MASS_CHANGE_SHARE = 0.5
MASS_CHANGE_MIN = 5

STORAGE_VERSION = 1
SERVICE_SYNC_NOW = "sync_now"
