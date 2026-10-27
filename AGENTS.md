# AGENTS.md

Home Assistant custom integration (HACS) that syncs two `todo.*` entities.

- Conventional Commits, branches `<type>/<slug>`, never push to `main`;
  always a pull request. Author `Sebastian Kornehl <sebastian@kornehl.org>`,
  `Co-Authored-By` trailer when an agent did the work. English in code and docs.
- `custom_components/todo_sync/sync.py` is the whole merge logic and must not
  import Home Assistant, so `tests/test_sync.py` runs without it. Every
  behaviour change there needs a test.
- Side A may drop completed items (Alexa); keep that asymmetry - "absent on
  A" means checked off, never deleted.
- `strings.json`, `translations/en.json` and `translations/de.json` stay
  key-identical; `en.json` is a copy of `strings.json`.
