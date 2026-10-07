# Data and storage

## Where things live

| What | Where (Windows) |
|---|---|
| Database | `%APPDATA%\HomingPigeon\mailer.db` (SQLite, WAL mode) |
| Encrypted email password | `%APPDATA%\HomingPigeon\secrets.dat` |
| Exports, logs, DKIM keys | `exports\`, `logs\`, `keys\` in the same folder |
| The program itself | `%LOCALAPPDATA%\Programs\HomingPigeon` |

Paths come from `app/config.py`. Mac and Linux use the usual equivalents.
Updating or uninstalling the program never touches the data folder unless the
user ticks "delete my data" in Settings.

## Tables (`app/core/db.py`, `_SCHEMA`)

| Table | Holds | Notes |
|---|---|---|
| `schema_info` | One row: the schema version | See migrations below |
| `settings` | Key/value, values stored as JSON | `db.get_setting` / `db.set_setting` |
| `contacts` | One row per address | `email` is unique, case-insensitive. Spreadsheet columns other than email/company/person go into `extra_json` |
| `template_sets`, `subjects`, `bodies` | My message | One set in practice. Bodies are typed text (or HTML if the user wrote HTML) |
| `campaigns` | One per send run setup | |
| `campaign_recipients` | Who is in which campaign and their status | `pending`, `retry`, `sent`, `failed`, `bounced`, `skipped`. This is what prevents emailing someone twice. Cascades away if the contact is deleted |
| `sent_log` | Permanent history for the Sent emails page (v0.6.2) | A copy of the contact's details plus the finished email, zlib-compressed in `body_z`. Not linked by foreign key, so it survives contact deletion and Clear list. Only the user deletes from it |
| `suppression` | Do-not-contact list | Bounces and unsubscribe replies land here automatically and survive Clear list |
| `events` | Activity log | |
| `warmup_state` | Daily cap ramp | |
| `scores` | Spam score history | |
| `imap_state`, `inbox_messages` | Inbox check position and the readable inbox | Trimmed to 800 messages |

### sent_log in detail

- Written by `SendWorker._record()` in `app/core/sender.py` after every attempt
  that ends `sent`, `failed` or `bounced` (temporary `retry` is not recorded).
- One row per (campaign, contact): a retry that later succeeds updates the same
  row (`ON CONFLICT ... DO UPDATE`), adding to `attempts`.
- `imap_sync.py` sets `bounced_at`/`status='bounced'` and `replied_at` on it by
  email address. The Sent page also reads `contacts.replied_at/bounced_at` via a
  LEFT JOIN on email, using whichever is set.
- `db.sent_message(id)` returns a dict with `body_html` unpacked, for the viewer.
- `db.delete_sent(ids)` / `db.clear_sent()` touch `sent_log` only. Never make
  them touch `campaign_recipients`.
- Rows copied over from before v0.6.2 have no `body_z`; the viewer says so.

## Settings keys worth knowing

| Key | Meaning |
|---|---|
| `unsubscribe_note` | `true` (default): add the unsubscribe line and `List-Unsubscribe` header. Set by the switch on My message, Signature tab |
| `contact_columns` | Every extra column heading ever imported, in order (v0.6.2). Read by `importer.extra_columns()`; reset by Clear whole list |
| `template_set_id` | The saved My message set |
| `sender_name`, `sender_email`, `reply_to` | The From identity |
| `smtp_*`, `imap_*` | Mail server settings (password is not here, see `credentials.py`) |
| `attach_mode`, `attachment_path`, `link_url`, `link_text` | Brochure: link, attachment or none |
| `delay_min_s`, `delay_max_s`, `window_start`, `window_end`, `weekdays_only`, `skip_holidays`, `holidays` | Pacing and office hours |
| `warmup_enabled`, `manual_daily_cap`, `provider_limit*` | Daily cap |
| `appearance`, `text_size`, `high_contrast`, `bold_text`, `date_format`, `time_format`, `start_page`, `last_page` | Look and feel (`app/core/prefs.py`) |
| `contacts_sort` | Remembered sort on My contacts |
| `language` | `en`, `ar`, `de`, `es` or `fr`. Empty until chosen in Settings: then the computer's language is used if supported, else English |

## Migrations

Users upgrade in place and keep their database, so every schema change needs:

1. The new `CREATE TABLE IF NOT EXISTS` / index in `_SCHEMA` (runs on every start).
2. For anything else (new columns on an existing table, data copies): a step in
   `_migrate()` guarded by `if row["version"] < N:`.
3. `SCHEMA_VERSION` bumped to N.
4. A test that builds an old-version database and opens it with `db.init()`
   (see `test_upgrading_copies_the_old_history_across` in `tests/test_core.py`).

`ALTER TABLE ... ADD COLUMN` is the safe way to add a column; SQLite cannot drop
or rename freely on old versions, so prefer adding.

History: version 1 was every release up to v0.6.1. Version 2 (v0.6.2) added
`sent_log` and copies existing sends into it (`backfill_sent_log`).
