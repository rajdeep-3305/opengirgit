# UI translations

OpenGirGit ships a tiny, offline translation layer: strings are keyed by their
**English source text** and looked up in a plain JSON catalog. Nothing is
fetched at runtime and a missing catalog (or missing entry) simply falls back to
English, so a half-finished translation is never worse than none.

## Use one

* Settings → **Behaviour → Interface language** (or `OPENGIRGIT_UI_LANGUAGE`,
  or `ui_language` in `~/.opengirgit/config.json`).
* `"auto"` follows the desktop locale; `en` is always available.

## Add a language

```bash
cp client/opengirgit/translations/en.json client/opengirgit/translations/<code>.json
# translate the *values*, keep the keys exactly as they are
```

* `<code>` is an ISO 639-1 code (`fr`, `pt`, `uk`, …). Regional variants work
  too: name the file `pt_BR.json` and select `pt_BR`. An unshipped region
  (`pt_PT`) falls back to the language file (`pt`) when that exists, and to
  English otherwise.
* Keep every `{placeholder}` intact — they are filled with `.format(...)`.
* Friendly names for the picker live in `client/opengirgit/i18n.py`
  (`LANGUAGE_NAMES`); unknown codes are shown verbatim.
* Saving the choice in Settings applies it immediately; `auto` follows the
  desktop locale at startup.

## Verify

```bash
python tools/collect_strings.py --check   # catalog is in sync with the code
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_client_i18n.py
```

`tools/collect_strings.py` re-generates `en.json` from every `tr("…")` literal
in `client/opengirgit/`. CI-friendly `--check` mode fails when the catalog is
stale (i.e. someone added a string without refreshing it).
