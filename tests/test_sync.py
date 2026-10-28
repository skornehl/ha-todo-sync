"""Tests for the pure merge in custom_components/todo_sync/sync.py.

Loaded by file path so the tests need no Home Assistant installation (the
package __init__ imports homeassistant).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

_PATH = Path(__file__).parents[1] / "custom_components" / "todo_sync" / "sync.py"
_spec = importlib.util.spec_from_file_location("todo_sync_merge", _PATH)
sync = importlib.util.module_from_spec(_spec)
sys.modules["todo_sync_merge"] = sync
_spec.loader.exec_module(sync)

OPEN, DONE, Item = sync.OPEN, sync.DONE, sync.Item
GRACE = 1200


def a(*names, done=()):
    return [Item(f"a-{n}", n, OPEN) for n in names] + [Item(f"a-{n}", n, DONE) for n in done]


def b(*names, done=()):
    return [Item(f"b-{n}", n, OPEN) for n in names] + [Item(f"b-{n}", n, DONE) for n in done]


def ops(result):
    return sorted((x.side, x.op, x.summary, x.status) for x in result.actions)


def run(a_items, b_items, snapshot=None, pending=None, now=1000.0):
    # confirm=0: these tests cover the merge rules, not incomplete reads.
    return sync.merge(a_items, b_items, snapshot or {}, pending or {}, now, GRACE, 0)


def settled(result, now=1000.0):
    """Snapshot after the actions were applied and are visible on both sides."""
    a_items = [Item(f"a-{k}", v["summary"], OPEN) for k, v in result.snapshot.items() if v["a"]]
    b_items = [
        Item(f"b-{k}", v["summary"], v["b"]) for k, v in result.snapshot.items() if v["b"]
    ]
    return a_items, b_items


# -- first sync ------------------------------------------------------------------


def test_first_sync_copies_alexa_items_into_empty_keep():
    r = run(a("Milch", "Brot"), [])
    assert ops(r) == [("b", "add", "Brot", OPEN), ("b", "add", "Milch", OPEN)]


def test_first_sync_merges_both_lists():
    r = run(a("Milch"), b("Eier", done=("Mehl",)))
    assert ops(r) == [("a", "add", "Eier", None), ("b", "add", "Milch", OPEN)]
    assert r.snapshot["mehl"] == {"summary": "Mehl", "a": False, "b": DONE}


def test_names_match_case_and_whitespace_insensitively():
    r = run(a("gurken"), b("Gurken "))
    assert r.actions == []


# -- steady state and no ping-pong -----------------------------------------------


def test_second_run_after_applying_is_a_no_op():
    r1 = run(a("Milch"), b("Eier"))
    a_items, b_items = settled(r1)
    r2 = run(a_items, b_items, r1.snapshot, r1.pending, now=1010)
    assert r2.actions == []


# -- changes on A (Alexa) --------------------------------------------------------


def test_item_added_on_alexa_is_added_to_keep():
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    r = run(a("Milch", "Käse"), b("Milch"), snap)
    assert ops(r) == [("b", "add", "Käse", OPEN)]


def test_item_gone_from_alexa_is_checked_off_in_keep():
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    r = run([], b("Milch"), snap)
    assert ops(r) == [("b", "set_status", "Milch", DONE)]
    assert r.snapshot["milch"] == {"summary": "Milch", "a": False, "b": DONE}


def test_item_readded_on_alexa_reopens_it_in_keep():
    snap = {"milch": {"summary": "Milch", "a": False, "b": DONE}}
    r = run(a("Milch"), b(done=("Milch",)), snap)
    assert ops(r) == [("b", "set_status", "Milch", OPEN)]


# -- changes on B (Keep) ---------------------------------------------------------


def test_item_checked_off_in_keep_is_completed_on_alexa():
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    r = run(a("Milch"), b(done=("Milch",)), snap)
    assert ops(r) == [("a", "set_status", "Milch", DONE)]


def test_item_unchecked_in_keep_is_added_to_alexa_again():
    snap = {"milch": {"summary": "Milch", "a": False, "b": DONE}}
    r = run([], b("Milch"), snap)
    assert ops(r) == [("a", "add", "Milch", None)]


def test_item_deleted_in_keep_is_removed_from_alexa():
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    r = run(a("Milch"), [], snap)
    assert ops(r) == [("a", "set_status", "Milch", DONE)]
    assert "milch" not in r.snapshot


def test_completed_item_deleted_in_keep_is_forgotten():
    snap = {"milch": {"summary": "Milch", "a": False, "b": DONE}}
    r = run([], [], snap)
    assert r.actions == [] and r.snapshot == {}


# -- conflicts -------------------------------------------------------------------


def test_both_sides_changed_keeps_the_item():
    # Checked off on Alexa (gone) while re-added... both changed: deleted in
    # Keep and re-added on Alexa -> keep it.
    snap = {"milch": {"summary": "Milch", "a": False, "b": DONE}}
    r = run(a("Milch"), [], snap)
    assert ops(r) == [("b", "add", "Milch", OPEN)]


def test_duplicate_names_in_one_list_are_ignored():
    r = run(a("Milch", "milch"), [])
    assert ops(r) == [("b", "add", "Milch", OPEN)]


# -- pending writes ----------------------------------------------------------------


def test_add_not_yet_visible_on_keep_is_not_treated_as_deletion():
    r1 = run(a("Milch"), [])
    # Keep has not picked up the add yet on the next run.
    r2 = run(a("Milch"), [], r1.snapshot, r1.pending, now=1100)
    assert r2.actions == []
    assert "b:milch" in r2.pending


def test_pending_expires_after_grace_period():
    r1 = run(a("Milch"), [])
    r2 = run(a("Milch"), [], r1.snapshot, r1.pending, now=1000 + GRACE + 1)
    # Never arrived on Keep: treated as deleted there -> removed from Alexa.
    assert ops(r2) == [("a", "set_status", "Milch", DONE)]


def test_pending_is_cleared_once_visible():
    r1 = run(a("Milch"), [])
    r2 = run(a("Milch"), b("Milch"), r1.snapshot, r1.pending, now=1100)
    assert r2.actions == [] and r2.pending == {}


def test_check_off_not_yet_visible_on_alexa_is_not_undone():
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    r1 = run(a("Milch"), b(done=("Milch",)), snap)
    # Alexa still shows the item on the next run.
    r2 = run(a("Milch"), b(done=("Milch",)), r1.snapshot, r1.pending, now=1050)
    assert r2.actions == []


# -- incomplete reads ------------------------------------------------------------

CONFIRM = 360


def run_c(a_items, b_items, snapshot, pending=None, now=1000.0):
    return sync.merge(a_items, b_items, snapshot, pending or {}, now, GRACE, CONFIRM)


def test_item_briefly_missing_on_alexa_is_not_checked_off():
    # The real incident: one read of the Alexa list lacked 4 of 17 items.
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    r1 = run_c([], b("Milch"), snap)
    assert r1.actions == []
    assert r1.snapshot["milch"]["a"] is True
    # Back on the next read: nothing happened, the marker is gone.
    r2 = run_c(a("Milch"), b("Milch"), r1.snapshot, r1.pending, now=1100)
    assert r2.actions == [] and r2.pending == {}


def test_item_missing_for_longer_than_confirm_is_checked_off():
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    r1 = run_c([], b("Milch"), snap)
    r2 = run_c([], b("Milch"), r1.snapshot, r1.pending, now=1000 + CONFIRM)
    assert ops(r2) == [("b", "set_status", "Milch", DONE)]


def test_item_briefly_missing_on_keep_is_not_removed_from_alexa():
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    r1 = run_c(a("Milch"), [], snap)
    assert r1.actions == []
    r2 = run_c(a("Milch"), [], r1.snapshot, r1.pending, now=1000 + CONFIRM)
    assert ops(r2) == [("a", "set_status", "Milch", DONE)]


def test_explicit_check_off_in_keep_is_not_delayed():
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    r = run_c(a("Milch"), b(done=("Milch",)), snap)
    assert ops(r) == [("a", "set_status", "Milch", DONE)]


def test_missing_on_keep_while_alexa_confirmed_gone_adds_no_duplicate():
    # Gone from Alexa for long enough, but this Keep read lacks the item:
    # Keep must not get a second "Milch".
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    pending = {"gone:a:milch": {"since": 1000 - CONFIRM}}
    r = run_c([], [], snap, pending)
    assert all(not (x.side == "b" and x.op == "add") for x in r.actions)
    assert r.snapshot["milch"]["b"] == OPEN


def test_readded_on_alexa_while_missing_on_keep_adds_no_duplicate():
    snap = {"milch": {"summary": "Milch", "a": False, "b": DONE}}
    r = run_c(a("Milch"), [], snap)
    assert all(not (x.side == "b" and x.op == "add") for x in r.actions)


def test_completed_on_alexa_is_checked_off_in_keep_at_once():
    # Still listed on Alexa, but completed: an explicit check-off, no delay.
    snap = {"milch": {"summary": "Milch", "a": True, "b": OPEN}}
    r = run_c([Item("a-Milch", "Milch", DONE)], b("Milch"), snap)
    assert ops(r) == [("b", "set_status", "Milch", DONE)]
