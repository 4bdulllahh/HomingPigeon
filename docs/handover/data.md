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
| `template_sets`, `subjects`, `bodies` | My message | One set in practice. Bodies are typed text from before v0.7.3, or HTML from the formatting editor. `footer_html` is the small print under the signature (v0.7.3) |
| `campaigns` | A round of sending. The newest one is current (`db.current_campaign()`); only "Start a new campaign" makes another (v0.7.2) | |
| `campaign_recipients` | Who is queued in which campaign and their status | `pending`, `retry`, `sent`, `failed`, `bounced`, `skipped`. `attempts` caps retries at `config.MAX_SEND_ATTEMPTS`. Cascades away if the contact is deleted, which is why `contacted` exists |
| `contacted` | Who was emailed in each campaign, by address (v0.7.2) | Primary key (email, campaign_id), email case-insensitive. Status `sent`, `bounced` or `failed`. **This is what stops emailing someone twice**: it survives deleting contacts, Clear list, re-imports and clearing the Sent history. Only `db.allow_again()` and a new campaign let someone be emailed again |
| `sent_log` | Permanent history for the Sent emails page (v0.6.2) | A copy of the contact's details plus the finished email, zlib-compressed in `body_z`. Not linked by foreign key, so it survives contact deletion and Clear list. Only the user deletes from it |
| `suppression` | Do-not-contact list | Bounces and unsubscribe replies land here automatically and survive Clear list |
| `events` | Activity log | |
| `warmup_state` | Daily cap ramp | |
| `scores` | Spam score history | |
| `designs` | Email designs (v0.7.1) | `data` is the design as JSON, pictures included. See `app/core/design.py` |
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
  them touch `campaign_recipients` or `contacted`.

### Never emailing someone twice (v0.7.2)

- `db.queue_contacts(campaign)` is one `INSERT ... SELECT` with two `NOT EXISTS`
  lookups (do-not-contact list and `contacted`), both on indexed email columns.
- `SendWorker` checks `db.already_contacted()` again right before each email and
  records the final outcome with `db.record_contacted()` (inside `_record`).
- Contacts are sent in `contacts.id` order, which is the spreadsheet's order.
- `db.contact_send_status(campaign)` is the SQL behind the Status column and
  the Show filter on My contacts.
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
| `warmup_preset`, `warmup_ramp` | Warm-up plan: `very_safe`, `safe` (default), `faster` or `custom`, and the custom list of daily caps (v0.7.1) |
| `design_id`, `brand_kit` | The design emails are sent with (0 = plain) and the brand kit (v0.7.1) |
| `appearance`, `text_size`, `high_contrast`, `bold_text`, `date_format`, `time_format`, `start_page`, `last_page` | Look and feel (`app/core/prefs.py`). `appearance` is Dark, Light, System, a key of `themes.PRESETS`, or `custom:` plus a theme name |
| `custom_themes` | The user's own themes, a list of theme dicts (`app/core/themes.py`). Damaged entries are skipped when read |
| `nav_order`, `nav_hidden` | Sidebar order and hidden pages, lists of page keys. `[]` is the original order (`prefs.ordered`) |
| `contacts_sort` | Remembered sort on My contacts |
| `auto_imap_sync` | Check the inbox in the background (default on). The timer is on `MainWindow` |
| `imap_folder_marks` | `{folder: [uidvalidity, last uid]}` for the inbox and the Junk folder (v0.7.2) |
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
`sent_log` and copies existing sends into it (`backfill_sent_log`). Version 3
(v0.7.1) added the `designs` table; nothing to copy. Version 4 (v0.7.2) added
`contacted` and fills it from `sent_log` and `campaign_recipients`
(`backfill_contacted`), so nobody already emailed is emailed again after the update.
Version 5 (v0.7.3) added `template_sets.footer_html`; nothing to copy.
