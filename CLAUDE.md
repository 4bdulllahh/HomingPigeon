# HomingPigeon: notes for Claude

A Windows-first PyQt6 desktop app that sends personalised business email safely
(warm-up, pacing, spam scoring, bounce and unsubscribe handling). It is a product
for non-technical users: free beta now, sold later. Everything the user sees must
be plain English, and is shown in the user's language: English, Arabic (right to
left), German, Spanish or French.

**Read [docs/handover/README.md](docs/handover/README.md) before changing anything.**
It links to the architecture, the database, a map of every feature and the
release history.

## Rules that are easy to break

- No em dashes, en dashes or typographic ellipses anywhere (code, UI text, docs).
  Use commas, colons, full stops and three plain dots. `tests/test_ui.py` fails
  the build if one slips in.
- First run stays blank. Never pre-fill templates, contacts or settings; examples
  appear only when the user presses "Show me an example".
- Nothing slow on the UI thread. SMTP, IMAP, DNS, spreadsheets and scoring go
  through `app/workers/` (`Task` or a `Worker`).
- `app/core/` has no UI imports. Business rules live there and are unit tested.
- Never `git push` unless the user asks. Local commits are fine.
- Database changes need a migration step in `db._migrate()` and a bump of
  `SCHEMA_VERSION`, because users upgrade in place and keep their data.
- Deleting from the Sent emails history must never touch `campaign_recipients`;
  that table is what stops a person being emailed twice.
- **Every new or changed piece of on-screen text needs translating** into ar, de,
  es and fr, or `tests/test_i18n.py` fails. Write the English, then run
  `python tools/i18n.py missing de` (and ar, es, fr), translate the numbered
  lines into a file and `python tools/i18n.py merge de FILE`. See
  [docs/handover/languages.md](docs/handover/languages.md).
- Text with a value in it is a template: `t("{count} contacts imported",
  count=n)`. Never an f-string or English fragments glued together, which
  cannot be translated. Never call `t()` at import time.

## Everyday commands

```
pip install -r requirements-dev.txt
python run.py                      # run the app
python -m pytest tests/ -q         # all tests, headless
python tools/build_installer.py    # dist/HomingPigeon-vX.Y.Z.zip
```
