# To-do List Sync

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=white)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Release](https://img.shields.io/github/v/release/skornehl/ha-todo-sync?style=for-the-badge&color=6366F1)](https://github.com/skornehl/ha-todo-sync/releases)
[![Home Assistant 2025.6+](https://img.shields.io/badge/Home%20Assistant-2025.6%2B-18BCF2?style=for-the-badge&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![Checks](https://img.shields.io/github/actions/workflow/status/skornehl/ha-todo-sync/validate.yml?branch=main&style=for-the-badge&label=checks)](https://github.com/skornehl/ha-todo-sync/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/skornehl/ha-todo-sync?style=for-the-badge&color=9333EA)](LICENSE)

Keeps two Home Assistant to-do lists in step, in both directions - for
example the **Alexa shopping list** and a **Google Keep** checklist (via
[Google Keep Sync](https://github.com/watkins-matt/home-assistant-google-keep-sync)).
Any two `todo.*` entities work; the integration only talks to Home
Assistant, never to Alexa or Google directly.

## How it works

Items are matched by name (case and spacing do not matter). After every
sync the integration remembers the common state, so it can tell "added on
one side" from "deleted on the other side".

| Change | Result |
|---|---|
| Item added on either side | added on the other side |
| Item checked off in list B | completed (and so removed) in list A |
| Item unchecked in list B | added to list A again |
| Item disappears from list A | checked off in list B |
| Item deleted in list B | removed from list A |

List A is meant for lists that cannot keep checked-off items: the Alexa
shopping list removes an item as soon as it is checked off. Put that list
in A and the list that keeps completed items (Keep) in B.

Syncs run 10 seconds after a change on either list and every 5 minutes.
Changes made in Google Keep only reach Home Assistant when Google Keep
Sync polls (every 15 minutes by default).

### Safety

- If a list is unavailable, nothing is synced.
- If more than half of the items (at least 5) would be removed or checked
  off at once, the sync is skipped: that is almost always one list being
  temporarily empty, not a user clearing it. Call `todo_sync.sync_now`
  with `force: true` if it really was intended.
- A write that is not yet visible on the other side (Keep is polled) is
  not mistaken for a change for up to 20 minutes.
- An item that disappears from a list is only treated as checked off or
  deleted after it has been missing for at least 6 minutes (in practice
  6 to 10, depending on when the next sync runs): a single read can be
  incomplete. While an item is missing but not yet confirmed gone, nothing
  is written for it to that list. Checking off an item (it stays in the list, marked done) is
  synced right away.

The sensor *Last sync* shows the time of the last successful sync, the
last error and the last changes.

## Installation

1. HACS → Custom repositories → `https://github.com/skornehl/ha-todo-sync`
   (type *Integration*) → install **To-do List Sync**, restart Home Assistant.
2. Settings → Devices & services → Add integration → *To-do List Sync*,
   pick list A (e.g. `todo.einkaufsliste`) and list B (e.g. the Keep list).

The first sync copies every item that exists on only one side to the
other side.

## License

MIT
