"""Pure three-way merge of two to-do lists. No Home Assistant imports, so it
can be tested on its own.

Side A may be a list that cannot hold completed items (the Alexa shopping
list: checking an item off there removes it). For such a side, "absent"
and "completed" mean the same thing, so A is modelled as a set of open
items only. Side B (e.g. Google Keep) keeps completed items.

The merge compares both lists with the state after the last successful
sync (the snapshot). That is what tells "added on one side" apart from
"removed on the other side", which a plain two-way diff cannot do.

Writes to a side are not always visible immediately on the next read (a
remote service polled every few minutes). Every write is therefore
remembered as *pending* with the value it should produce; until the side
shows that value or the grace period ends, the expected value is used
instead of the stale one, so a sync never undoes its own writes.

Reads can also be incomplete for a moment (the Alexa shopping list add-on
once returned 13 of 17 items). An item that disappears from a side is
therefore only treated as checked off or deleted once it has been missing
for `confirm` seconds; until then it counts as still there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

OPEN = "needs_action"
DONE = "completed"

_SPACES = re.compile(r"\s+")


def item_key(summary: str) -> str:
    """Items are matched by name, case- and whitespace-insensitively."""
    return _SPACES.sub(" ", summary).strip().casefold()


@dataclass(frozen=True)
class Item:
    uid: str | None
    summary: str
    status: str


@dataclass(frozen=True)
class Action:
    side: str  # "a" | "b"
    op: str  # "add" | "set_status" | "remove"
    key: str
    summary: str
    uid: str | None = None
    status: str | None = None


@dataclass
class MergeResult:
    actions: list[Action] = field(default_factory=list)
    snapshot: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)


def index(items: list[Item]) -> dict[str, Item]:
    """First item per key wins; duplicates within one list are ignored."""
    out: dict[str, Item] = {}
    for item in items:
        key = item_key(item.summary)
        if key and key not in out:
            out[key] = item
    return out


def merge(
    a_items: list[Item],
    b_items: list[Item],
    snapshot: dict[str, dict[str, Any]],
    pending: dict[str, dict[str, Any]],
    now: float,
    grace: float,
    confirm: float,
) -> MergeResult:
    """Compute the actions that bring A and B in line with each other.

    snapshot: key -> {"summary", "a": bool (open on A), "b": OPEN|DONE|None}
    pending: "<side>:<key>" -> {"expect": value, "ts": float}, plus
             "gone:<side>:<key>" -> {"since": float} for items that went
             missing and are not yet confirmed gone
    """
    a_all = index(a_items)
    b_idx = index(b_items)
    a_open = {k: v for k, v in a_all.items() if v.status == OPEN}

    result = MergeResult()
    still_pending: dict[str, dict[str, Any]] = {}

    def effective(side: str, key: str, actual: Any) -> Any:
        """Actual value, unless a recent write of ours has not arrived yet."""
        entry = pending.get(f"{side}:{key}")
        if entry is None or entry["expect"] == actual or now - entry["ts"] > grace:
            return actual
        still_pending[f"{side}:{key}"] = entry
        return entry["expect"]

    def confirmed_gone(side: str, key: str) -> bool:
        """True once the item has been missing on `side` for `confirm` seconds."""
        marker = f"gone:{side}:{key}"
        since = pending.get(marker, {}).get("since", now)
        if now - since >= confirm:
            return True
        still_pending[marker] = {"since": since}
        return False

    for key in set(a_all) | set(b_idx) | set(snapshot):
        a_item = a_all.get(key)
        b_item = b_idx.get(key)
        a = effective("a", key, key in a_open)
        b = effective("b", key, b_item.status if b_item else None)
        s = snapshot.get(key)
        # Assumed values stand in for a read that may be incomplete. They
        # must never trigger a write to that side: there is no item to
        # update, and adding one would create a duplicate once the read is
        # complete again.
        a_assumed = b_assumed = False
        if s is not None:
            # Only an item that is really missing; one that is still there
            # but completed was checked off explicitly and syncs at once.
            if s["a"] and a_item is None and not a and not confirmed_gone("a", key):
                a, a_assumed = True, True
            if s["b"] is not None and b is None and not confirmed_gone("b", key):
                b, b_assumed = s["b"], True
        summary = (
            (a_item.summary if a_item else None)
            or (b_item.summary if b_item else None)
            or (s or {}).get("summary", key)
        )

        a_t, b_t = _decide(a, b, s)
        # Defer changes to a side whose read is in doubt; the next run
        # decides again with a complete read or a confirmed absence.
        if a_assumed and a_t != a:
            a_t = a
        if b_assumed and b_t != b:
            b_t = b

        if a_t != a:
            if a_t:
                if a_item is not None:  # present but completed (transient)
                    result.actions.append(Action("a", "set_status", key, summary, a_item.uid, OPEN))
                else:
                    result.actions.append(Action("a", "add", key, summary))
            elif a_item is not None:
                result.actions.append(Action("a", "set_status", key, summary, a_item.uid, DONE))
            still_pending[f"a:{key}"] = {"expect": a_t, "ts": now}

        if b_t != b:
            if b_t is None:
                if b_item is not None:
                    result.actions.append(Action("b", "remove", key, summary, b_item.uid))
            elif b_item is None:
                result.actions.append(Action("b", "add", key, summary, status=b_t))
            else:
                result.actions.append(Action("b", "set_status", key, summary, b_item.uid, b_t))
            still_pending[f"b:{key}"] = {"expect": b_t, "ts": now}

        if a_t or b_t is not None:
            result.snapshot[key] = {"summary": summary, "a": a_t, "b": b_t}

    result.pending = still_pending
    return result


def _decide(a: bool, b: str | None, s: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Target (open on A, status on B) for one item."""
    if s is None:
        # Unknown so far: whatever exists anywhere is new and is copied over.
        if a:
            return True, OPEN  # also reopens an old completed copy on B
        if b == OPEN:
            return True, OPEN
        return False, b  # completed on B only, or nothing at all

    a_changed = a != s["a"]
    b_changed = b != s["b"]

    if not a_changed and not b_changed:
        return a, b

    if a_changed and not b_changed:
        if a:  # (re)added on A
            return True, OPEN
        # checked off or removed on A: check it off on B, keep it there
        return False, (DONE if b is not None else None)

    if b_changed and not a_changed:
        if b == OPEN:  # added or unchecked on B
            return True, OPEN
        return False, b  # checked off (DONE) or deleted (None) on B

    # Both changed since the last sync: keep the item if either side wants it.
    if a or b == OPEN:
        return True, OPEN
    return False, b
