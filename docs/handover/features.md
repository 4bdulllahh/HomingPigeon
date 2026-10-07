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

- Tabs: Subjects, Message, Signature, Preview & score. All built up front.
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

- Reads new mail over IMAP from the last UID seen. Bounces are parsed for the
  failed address; hard bounces are suppressed. Replies from known contacts set
  `replied_at`. Everything read is stored in `inbox_messages` for reading.

## Other pages

- Home (`dashboard.py`): counts and status. Start here (`guide.py`): checklist
  that ticks itself from real state. My email account (`account.py`): SMTP/IMAP
  with provider presets. Domain check (`deliverability.py`): SPF/DKIM/DMARC.
  Sending options (`campaign.py`): brochure, pacing, warm-up. Settings
  (`settings.py`): appearance, dates, backup/restore, update check, uninstall.
