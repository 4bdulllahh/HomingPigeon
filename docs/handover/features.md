# Feature map

Where each feature lives and how it works. Paths are from the repository root.

## Importing contacts (My contacts, Import tab)

- UI: `app/ui/pages/contacts.py` (`_build_import`, `_preview_ready`, `_start_import`).
- Reading the file: `importer.read_sheet` (pandas, every cell read as text).
- Column guessing: `importer.detect_columns` scores headings against
  `EMAIL_HINTS`, `COMPANY_HINTS`, `PERSON_HINTS`; the email column is found by
  content first. The user can change the three choices before importing.
- **Every other column is kept** in `contacts.extra_json`, and its heading is
  saved in the `contact_columns` setting (`importer.remember_columns`). The
  import screen lists them under the column pickers.
- The import runs in `jobs.ImportWorker`: MX lookups first (no database lock),
  then rows committed in batches of 250.
- Dedupe, validation, typo domains, role accounts and the do-not-contact list
  are all applied in `importer.import_dataframe`.

## My contacts list

- Model: `app/models/contacts_model.py`, paged from SQLite 300 rows at a time.
- Status and Last sent columns come from `db.contact_send_status()` and the
  `contacted` table. "Show:" filters by status in SQL. Right-click "Send to this
  person again" calls `Page.allow_again()` (also on Sent emails).
- Columns: the fixed ones, then every heading from `importer.extra_columns()`
  (capped at 200 to survive junk sheets).
- Delete selected (button, Delete key, right-click), "Delete and never contact
  again", Clear whole list (runs on a worker; keeps the do-not-contact list and
  the Sent history; resets `contact_columns`).

## Merge tags and spintax

- `app/core/merge.py`. `TAG_PATTERN` accepts anything between `{{` and `}}`
  except braces and new lines, so headings like `{{Phone No.}}` or
  `{{Website / URL}}` work. Matching ignores case and spaces.
- Built-in tags: `FirstName`, `FullName`, `Company`, `Email`, `Domain`. Extra
  columns come from `extra_json`. A built-in always wins over a column of the
  same name.
- `importer.merge_tag_names()` = built-ins + every extra column. Used by the
  "Personal touch" buttons and by the scorer to flag unknown tags.
- Spintax `{Hi|Hello}` is expanded first; tags are shielded from it.

## My message (`app/ui/pages/templates.py`)

- Tabs: Subjects, Message, Signature, Footer, Preview & score. All built up front.
- **Formatting (v0.7.3).** Message, Signature and Footer are `RichBox`es with a
  `RichToolbar` (`app/ui/widgets/rich_text.py`). `editor_html` loads old plain
  text unchanged; `document_to_html` writes the document back as minimal HTML
  (`<p>`, `<br>`, `<ul>`, `<strong>`, a `style` only when not the default),
  because the scorer counts formatting. Pictures are stored as data: URIs and
  turned into cid: parts at send time (`composer.inline_pictures`). Subjects stay
  plain text. The footer is sent small and grey (`composer.footer_block`).
- "Personal touch" buttons show **every** tag and are rebuilt in `on_show()`
  when the tag list changes (`_refresh_tag_bars`), so a new import shows up
  without a restart.
- **Import from a spreadsheet** (`_import_sheet`, `importer.read_templates`):
  headings containing "subject" are subjects; "message", "body", "email",
  "content", "text" or "template" are messages; "signature" is the signature.
  No recognised headings: first column subjects, second messages. Every sheet in
  the workbook is read. If the user already has text, they choose Add or
  Replace. Unknown tags are reported in the toast.
- **Get a blank sheet** (`importer.write_template_sample`) saves an .xlsx with
  Subject / Message / Signature columns pre-filled with the built-in examples.
- **Unsubscribe switch** on the Signature tab saves `unsubscribe_note`
  immediately.
- Typed text becomes HTML in `composer.text_to_html`; a message already
  containing `<p>`/`<br>` is left alone.

- **New boxes go to the top**: `_new_subject` / `_new_body` insert at index 0
  and renumber, and the cursor lands in the new box. Loading, examples and
  imports still append in order.
- **The toolbar stays in view**: the tags, style buttons and Add button are a
  `StickyBar`. It is built twice: one copy sits in the page, the other is shown
  pinned over the top of the scroll view once the first scrolls out of sight.
  Never reparent a widget while scrolling instead; Qt crashes if that happens
  while a window is closing.

## Email design (`app/ui/pages/design.py`, `app/core/design.py`)

- A design is JSON: `page` settings, a list of `blocks`, and `assets` (pictures
  as base64). `design.BLOCKS` lists every block type and its settings
  (`Field`s); the editor builds every settings form from that, so a new block
  needs a `BlockSpec`, a `_Renderer` method for the email and a `_draw_` method
  in `email_canvas.py` for the picture in the editor.
- Exactly one `message` block, which cannot be removed: it is where each
  person's message (one of the versions from My message) goes, with the
  signature and brochure link. The unsubscribe line goes in the footer block,
  or at the end without one.
- `design.render()` builds table-based HTML with inline styles and returns the
  pictures it used. `composer.assemble()` uses it when `Content.design` is set;
  `build_message` attaches the pictures as `multipart/related` parts (cid:),
  `preview_message` writes them in as data: URIs so a browser can show them.
- The canvas (`EmailCanvas`) draws the design with Qt widgets, not a browser
  engine (too big, and Smart App Control blocks parts of it). It follows the
  HTML closely; "Open in browser" shows the exact email.
- **My designs (v0.7.3).** The page opens on a library (`_show_library`): the
  user's designs as cards, then the starters with Blank first. Edits save a
  second after the last change (`_autosave`) and on leaving the page or closing
  the app (`before_close`). Each design is mirrored to
  `config.DESIGNS_DIR/<name>.hpdesign` on a worker; rename renames the file,
  delete sends it to the Recycle Bin. Tests point `DESIGNS_DIR` at a temp folder
  (`tests/conftest.py`).
- **Drag and drop (v0.7.2).** The Add panel is a list of `BlockRow`s with icons
  from the Fluent icon font (`theme.BLOCK_ICONS`). A tile or a block on the
  canvas starts a `QDrag` (`email_canvas.start_drag`); the canvas surface takes
  the drop, shows a blue line and emits `dropped`, and the page inserts or moves
  the block (`design.move_block`). Drags start from a `QTimer.singleShot(0)` so
  the rebuild after a drop never deletes the widget whose handler is running.
  Blocks are a flat list: dragging into the two columns or card is not possible.
- **Typing on the email.** Double-click a block in `email_canvas.INLINE` opens a
  `_Typing` editor over it; Enter (Ctrl+Enter for paragraphs) or clicking away
  keeps it, Esc cancels. Other blocks still jump to their first setting.
- **Resize handle.** Pictures, logos, videos, buttons and empty space get a
  `_Handle`; dragging it changes the setting in `email_canvas.RESIZE`, clamped
  to the field's limits. The handle stays shown while dragging, because hiding
  it would let go of the mouse.
- The floating toolbar is a move grip, copy and remove. The right panel shows
  the words, then "Look" (`QUICK_STYLE` / `QUICK_PAGE`), then "More options".
- Pictures go through `design.prepare_image` (Pillow) on a worker: rotated per
  EXIF, cut to 1200 px wide, recompressed; small animated GIFs kept as they are.
  Social icons and the video play button are drawn by Pillow at send time.
- Imported design files and stored designs pass `design.validate()`, which
  checks every value against its field.
- Starting designs (`design.STARTERS`, `design.starter`) are only created when
  the user picks one: first run stays blank.
- Settings: `design_id` is the design emails are sent with (0 = plain), set by
  "Send my emails with this design". `brand_kit` holds the logo, colours and
  font.

## Warm-up (`app/core/warmup.py`, Sending options)

- `PRESETS`: `very_safe`, `safe` (default) and `faster` (the pre-v0.7.1 ramp),
  plus `custom`, stored in `warmup_preset`. The custom plan is `warmup_ramp`, a
  list of daily caps; after the last day the last number holds.
- `build_ramp(start, step, stop)` fills the day boxes; `ramp_warnings()` flags a
  start above 50 or any day above the Faster plan.

## The spam score (`app/core/scorer.py`)

- Reads the **finished email**, not the parts: `score()` renders exactly what
  the Preview tab shows (same contact, subject, message and spintax choices via
  `subject_index`, `body_index`, `seed`) with signature, brochure link and
  unsubscribe line, then checks the subject, the whole text, every link (the
  signature's included), pictures, tags left over or blank for this contact.
- Also checks across every version: unknown tags and brace mistakes in any
  subject or message, variety, identity and DNS, attachment, signature.
- `report.landing` estimates Gmail's tab: `primary`, `promotions` or `spam`,
  from the bulk-mail signals in `_check_promotions` (unsubscribe line and
  header, links, pictures, formatting, sales words, length, attachment). Items
  in the "Promotions tab" category say what to change.
- The Preview tab calls it through `jobs.score_content` with the preview's own
  contact and choices, so "Next contact" scores another person's version.
- Trigger and sales word lists cover all five languages.

## Example messages (`app/core/examples.py`)

- One set per language, written to land in the main inbox: greeting by name,
  short plain paragraphs, no links, pictures, formatting or sales words, one
  closing question. A test scores every subject/message pair in every language
  and requires 90+ and "primary".
- The guide on My message ("How to write your email" → "Reaching the main
  inbox, not spam or Promotions") explains the same rules to the user.

## Languages

See [languages.md](languages.md). Settings → Language; `MainWindow.change_language()`.

## The unsubscribe line

- `composer.Content.unsubscribe_note`. When true, `assemble_html` appends the
  footer and `build_message` adds `List-Unsubscribe` and
  `List-Unsubscribe-Post`. When false, both are left out (they are what make
  Gmail file mail under Promotions).
- Unsubscribe **replies** are handled regardless: `imap_sync._classify` spots
  them (`is_unsubscribe`), suppresses the address and marks the contact invalid.
- The scorer gives a **low** finding when the line is off and the message has no
  opt-out wording of its own.

## Sending (`app/ui/pages/send.py`, `app/core/sender.py`)

- The Send page builds a `SendPlan` (content, identity, SMTP, pacing) and starts
  `SendWorker`. Status goes into `campaign_recipients` after every email.
- Safety: random delay between emails, office hours and weekdays, holidays, the
  warm-up daily cap, stop after 5 failures in a row or a bounce rate over 5%.
  The rate includes bounces the inbox check found for emails sent in this run
  (late bounces), read from `campaign_recipients`.
- **Campaigns (v0.7.2).** The Send page always uses `db.current_campaign()`;
  "Start a new campaign" (`db.start_new_campaign`) closes it and queues everyone
  again. Temporary failures retry up to `config.MAX_SEND_ATTEMPTS` (3) times.
- After each attempt `_record()` copies the email into `sent_log`.

## Sent emails (`app/ui/pages/sent.py`, `app/models/sent_model.py`)

- Reads `sent_log` (see [data.md](data.md)). Filters: all, sent with no reply,
  replied, bounced, failed. Search covers address, company, person, subject.
- Tiles: emails sent, replied, bounced, failed.
- **Double-click** (or right-click, "See the email that was sent") opens
  `SentEmailDialog`: To, From, Company, Sent, Outcome, attachment, error, and
  the message rendered in a white `QTextBrowser`. "Open in browser" and "Copy
  the text" buttons.
- **Delete selected** (button, Delete key, right-click) and **Clear history**,
  with confirmation, mirroring My contacts. These only tidy the list: nobody is
  emailed again because of them.
- Export to Excel: `exporter.export_sent`.

## Inbox (`app/ui/pages/inbox.py`, `app/core/imap_sync.py`)

- Reads new mail over IMAP from the last UID seen, per folder, and starts again
  from the last 30 days when the server's UIDVALIDITY changes. The Junk folder
  (found by its `\Junk` flag or a usual name) is read too, for bounces only.
- `MainWindow.check_inbox_in_background()` runs it every `AUTO_SYNC_MINUTES` (10)
  while the app is open; a lock in `imap_sync.sync` stops two checks overlapping.
- A bounce is matched to our email by the Message-ID in the copy it carries
  (`original_message_id`, looked up in `sent_log`), then by the report's
  recipient, then by a guess from the text. Hard bounces are suppressed; soft
  ones (full mailbox, server busy) go back to `retry` (`_retry_later`).
- "Still trying" notices (`is_delay`) are stored as `delay` and change nothing.
  Out-of-office answers (`is_auto_reply`) are stored as `autoreply` and do not
  count as replies. Replies from known contacts set `replied_at`. Everything read
  is stored in `inbox_messages` for reading.

## Other pages

- Home (`dashboard.py`): counts and status. Start here (`guide.py`): checklist
  that ticks itself from real state. My email account (`account.py`): SMTP/IMAP
  with provider presets. Domain check (`deliverability.py`): SPF/DKIM/DMARC.
  Sending options (`campaign.py`): brochure, pacing, warm-up. Settings
  (`settings.py`): appearance, smooth scrolling, dates, backup/restore, update
  check, uninstall.
- Scrolling (`app/ui/scrolling.py`): an app-wide event filter animates wheel
  scrolling and marks a scrollbar "hot" under the mouse so the QSS widens it.
