# Handover: start here

These notes are for whoever works on HomingPigeon next, person or Claude. They
explain what the code does and why, so a change can be made months later
without rediscovering everything.

| File | What it covers |
|---|---|
| [architecture.md](architecture.md) | How the app is put together: threads, layers, pages |
| [data.md](data.md) | The SQLite database, every table, settings keys, migrations |
| [features.md](features.md) | Where each feature lives and how it works, page by page |
| [working-on-it.md](working-on-it.md) | Conventions, tests, building and releasing, known traps |
| [changelog.md](changelog.md) | What changed in each release, newest first |

## The product in one paragraph

A small business imports a spreadsheet of leads, writes a few versions of a
subject and a message, and the app sends them one at a time from the user's
own mailbox over SMTP: slowly, in office hours, with a daily cap that rises as
the account warms up. It reads the inbox over IMAP to spot bounces, replies and
unsubscribe requests, and keeps a history of everything sent. Nothing leaves
the user's computer except mail to their own provider and DNS lookups.

## Who it is for

Non-technical office users. Every label, error and tooltip is written for
someone who has never heard of SMTP, HTML or merge tags. The app is a free beta
now and will be sold later, so it must behave like a product: no developer
jargon on screen, no pre-filled sample data on first run, and no data loss on
update.

## When you make a change

1. Read the relevant section of [features.md](features.md) first.
2. Keep business rules in `app/core/` and test them in `tests/test_core.py`.
3. UI behaviour gets a headless test in `tests/test_ui.py` where practical.
4. Run `python -m pytest tests/ -q`. All tests must pass.
5. Add a line to [changelog.md](changelog.md) under the next version.
6. If the database changed, read the migration section of [data.md](data.md).
