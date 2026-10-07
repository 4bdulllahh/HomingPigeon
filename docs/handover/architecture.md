# Architecture

## Layers

```
run.py                 starts QApplication, applies the theme, opens MainWindow
app/config.py          name, APP_VERSION, data paths, sending limits
app/core/              business rules. No Qt imports. Unit tested.
app/workers/           runs slow core functions off the UI thread
app/models/            Qt table models paged straight from SQLite
app/services/          backup/restore/uninstall (maintenance.py), self-update (updater.py)
app/ui/                main window, one module per page, shared widgets, theme
installer/setup_app.py the Windows installer (standard library only)
tools/                 build, icons, screenshots, Mac/Linux launcher
tests/                 pytest, headless Qt (QT_QPA_PLATFORM=offscreen)
```

The direction of imports is one way: `ui` uses `models`, `workers` and `core`;
`core` never imports anything from `ui`.

## app/core, module by module

| Module | Job |
|---|---|
| `db.py` | SQLite schema, migrations, one connection per thread, settings, suppression list, inbox store, sent history (`log_sent`, `sent_message`, `delete_sent`) |
| `importer.py` | Reads Excel/CSV, guesses the email/company/person columns, validates and dedupes, stores contacts. Also remembers every imported column heading and reads subjects/messages from a spreadsheet (`read_templates`) |
| `merge.py` | `{{Tag}}` merge tags and `{a\|b}` spintax, first-name cleanup |
| `composer.py` | Builds the MIME message: typed text to HTML, signature, brochure link, optional unsubscribe line and header |
| `scorer.py` | The spam score shown on My message |
| `sender.py` | The send worker thread: pacing, office hours, daily cap, circuit breakers, writes status after every email |
| `warmup.py` | The daily cap that rises over the first weeks |
| `imap_sync.py` | Reads the inbox: bounces, unsubscribe replies, genuine replies |
| `dns_tools.py` | MX, SPF, DKIM, DMARC checks and generators |
| `exporter.py` | Writes results back to Excel |
| `credentials.py` | Password storage (DPAPI on Windows) |
| `prefs.py` | User preferences and date/time formatting |

## Threads

- **UI thread**: Qt widgets only. Anything that may take more than a moment
  goes elsewhere.
- **`Task`** (`app/workers/base.py`): run one function on the Qt thread pool and
  get `on_result` / `on_error` back on the UI thread. Wrap callbacks that close
  over a page in `page.guard(...)`, because pages can be destroyed and rebuilt
  (Refresh, text size change) while a task is running.
- **`Worker`**: a longer job that reports progress (`ImportWorker`,
  `UpdateDownloadWorker`).
- **`SendWorker`** (`app/core/sender.py`): a plain `threading.Thread` that
  sends the campaign and pushes events onto a queue. `SendPump` in
  `app/workers/jobs.py` turns that queue into Qt signals for the Send page.
- SQLite allows one writer at a time. `db.connect()` gives each thread its own
  connection; writes are short and committed straight away. Long imports commit
  every 250 rows so the UI never waits on the lock for long.

## Pages

`app/ui/main_window.py` holds the sidebar (`NAV_ITEMS`) and builds each page the
first time it is opened. Page keys:

| Key | Module | Sidebar name |
|---|---|---|
| dashboard | pages/dashboard.py | Home |
| guide | pages/guide.py | Start here |
| account | pages/account.py | My email account |
| deliverability | pages/deliverability.py | Domain check |
| contacts | pages/contacts.py | My contacts |
| templates | pages/templates.py | My message |
| campaign | pages/campaign.py | Sending options |
| send | pages/send.py | Send emails |
| sent | pages/sent.py | Sent emails |
| inbox | pages/inbox.py | My inbox |
| settings | pages/settings.py | Settings |

Every page subclasses `Page` (`pages/base.py`). `on_show()` runs each time the
page becomes visible and should stay cheap. `busy_reason()` stops Refresh from
rebuilding a page with work in flight. Pages never call each other directly;
they go through `self.window_` (`go`, `ensure_page`, `notify`, `refresh_status`).

## Theme

`app/ui/theme.py` holds the colour tokens and builds one stylesheet. Changing
theme, contrast or bold text restyles; it never rebuilds widgets. Text size
does rebuild pages, which is why `guard()` exists. Widgets get their look from a
`role` property (`muted`, `hint`, `card`, `plain`, ...), not from inline styles.

## Updates and installing

- `installer/setup_app.py` becomes `HomingPigeon Setup.exe`. It installs a
  private Python into `%LOCALAPPDATA%\Programs\HomingPigeon` and pip-installs
  `requirements.txt`. User data is in `%APPDATA%\HomingPigeon` and survives
  updates and uninstalls.
- `app/services/updater.py` checks GitHub Releases on start-up, downloads the
  zip, checks its SHA-256 and hands over to `setup_app.py --update`.
- Some PCs (including the owner's) have Smart App Control, which blocks the
  unsigned Setup.exe. The `.bat` fallback in `installer/` installs using the
  signed python.org Python. Keep it working.
