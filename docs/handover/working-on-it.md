# Working on the code

## Conventions

- **Writing on screen.** Plain English for someone who has never set up email
  software. Say what to do, not how the code works. Short sentences. Then
  translate it: see [languages.md](languages.md). The build fails until every
  language has it.
- **No em dashes, en dashes or typographic ellipses**, anywhere in the
  repository. `test_no_em_dashes_or_typographic_ellipses_anywhere` enforces it.
  Use a comma, colon or full stop, and `...` typed as three dots.
- **First run is blank.** No sample contacts, templates or settings are created
  for the user. Examples only appear behind a "Show me an example" button.
- **Comments explain why**, in full sentences, matching the existing density.
  Look at a neighbouring function before writing a new one and match its style.
- **Widgets** come from `app/ui/widgets/` (`primary_button`, `secondary_button`,
  `danger_button`, `muted`, `hint`, `checkbox`, `DataTable`, `ConfirmDialog`,
  `ChoiceDialog`, `InfoDialog`...). Do not style widgets inline; use `role`.
- **Destructive actions** always go through `ConfirmDialog.ask(..., danger=True)`
  and say exactly what will and will not be affected.
- **Scale**: sizes in pixels are multiplied by `theme.text_scale()`.

## Tests

```
python -m pytest tests/ -q
```

- `tests/test_core.py`: business rules, no Qt. Module-wide temporary database.
- `tests/test_ui.py`: models, pages and widgets, headless. The `store` fixture
  gives each test a fresh database.
- `tests/test_i18n.py`: every language complete, templates, right to left,
  every page opening in every language.
- `tests/test_updater.py`, `tests/test_prefs.py`: updater and preferences.
- GitHub Actions runs the tests on every push and pull request
  (`.github/workflows/build.yml`).

To try sending without emailing anyone real:

```
python -m aiosmtpd -n -l localhost:1025
```

then set the server to `localhost`, port `1025`, security "None (testing only)".

## Building and releasing

1. Change `APP_VERSION` in `app/config.py` (for example `"v0.6.2 beta"`).
2. `python tools/build_installer.py` builds `dist/HomingPigeon Setup/` and
   `dist/HomingPigeon-vX.Y.Z.zip`. `dist/` and `build/` are git-ignored.
3. Commit. Push only when the owner asks.
4. On GitHub: Releases, Draft a new release, tag `vX.Y.Z`, publish. Actions
   builds and attaches the zip by itself (about 5 minutes), or drag the local
   zip into the release.
5. Installed copies see the new release next time they open and offer
   "Update now".

## Known traps

- **Refresh and text size rebuild pages.** Any `Task` callback that closes over
  a page must be wrapped in `page.guard(...)`, or it writes into a deleted
  widget and looks like a crash.
- **SQLite is single-writer.** Keep write transactions short. Never do network
  work (DNS, SMTP) while holding one.
- **`sqlite3.Row` has no `.get()`.** Convert with `merge.as_mapping(row)` or a
  dict comprehension first. Selecting two columns with the same name (for
  example `s.*` plus an alias) makes `row["name"]` return the first one.
- **Smart App Control** on the owner's PC blocks the unsigned Setup.exe. Test
  `installer/setup_app.py` with a python.org Python, and keep the `.bat`
  fallback installer working.
- **The `{{` pattern is generous on purpose** (any heading text). If you change
  `merge.TAG_PATTERN`, run the merge and spintax tests: spintax must not eat
  tags.
- **Deleting history is not deleting the send record.** `sent_log` is for the
  user to look at; `campaign_recipients` is what stops duplicates.
