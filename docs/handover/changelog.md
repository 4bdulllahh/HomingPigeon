# Changelog

Newest first. Add to the top when you change something.

## v0.6.3 beta

- Fixed the GitHub build, which failed one test on v0.6.2. GitHub installs the
  newest pandas (3.x), which writes a Windows line break into an .xlsx as two
  line breaks; the test fed one in and got an extra blank line back. The test
  now uses a plain line break, as Excel does, and a separate test checks every
  carriage-return variant directly. Reading line breaks from a spreadsheet
  (`importer._cell_text`) is also more forgiving of how different library
  versions unpack Excel's escaped `_x000D_`.
- Lesson: CI uses the newest versions allowed by `requirements.txt`, which can
  be newer than the ones on the development PC. When a test passes locally but
  fails on GitHub, compare `pandas`/`openpyxl` versions first.

## v0.6.2 beta

- **Unsubscribe line is optional.** New switch on My message, Signature tab
  (`unsubscribe_note`). Off removes both the footer and the `List-Unsubscribe`
  headers, which keeps mail out of Gmail's Promotions tab. Unsubscribe replies
  are still suppressed automatically. The scorer now treats a missing opt-out as
  a low finding instead of high.
- **Sent emails are kept for good.** New `sent_log` table (schema version 2)
  with a copy of each recipient's details and the finished email. Survives
  deleting contacts or clearing the list. Existing history is copied in on
  upgrade (without bodies).
- **See what was sent.** Double-click a row on Sent emails to open the email as
  it went out.
- **Delete from the Sent history.** Delete selected, Delete key, right-click,
  Clear history, with confirmations. Does not affect who has been contacted.
- **All spreadsheet columns are imported and usable.** The Personal touch row
  used to show only the first 8 tags and was never refreshed after an import;
  it now shows every column and updates on its own. Headings with punctuation
  (`Phone No.`, `Website / URL`) work as tags. My contacts shows every column
  (was 14). Column headings are remembered even when blank in early rows.
- **Import subjects and messages from a spreadsheet** on My message, plus "Get a
  blank sheet" for the layout.
- Handover docs (`docs/handover/`) and `CLAUDE.md` added.

## v0.6.1 beta

- My message: the whole page scrolls, typing behaves like an email program
  (Enter, Ctrl+Enter, empty line for a paragraph, "- " for bullets), a "How to
  write your email" guide.

## v0.6.0 beta

- The app updates itself: checks GitHub on start, "Update now" / "Update
  later" popup, unattended installer `--update` mode.
- README screenshots rendered from sample data (`tools/take_screenshots.py`).

## v0.5.x

- v0.5.1: installer shipped as one folder, so Defender stops reading it as a
  dropper. Smart App Control guide and `.bat` fallback.
- v0.5.0: the app stays usable during an import; sorting on My contacts;
  Refresh button.

## v0.4.x

- v0.4.2: readable inbox, wider sidebar, Setup closes on Finish.
- v0.4.0 / v0.4.1: interface rebuilt in PyQt6.

## v0.3.0 and earlier

- Settings page, new navigation, Windows installer with shortcuts and
  uninstaller, logo and icon.
