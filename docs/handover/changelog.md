# Changelog

Newest first. Add to the top when you change something.

## v0.7.3 beta

- **My designs page.** Email design opens on a page of the user's designs
  (thumbnail, "In use" badge, Open, More: rename, copy, use or stop using, save
  to a file, delete) and the starting designs, Blank first. The design picker,
  StarterDialog and the New design popup are gone: New design goes to the
  starting designs.
- **Rename in place.** The design's name sits next to Computer/Phone with a
  Rename button. Changes save themselves a second after the last edit
  (`Debouncer`), and on leaving the page or closing the app (`before_close`).
- **Design files.** Every design is also kept as a `.hpdesign` file in
  Documents\HomingPigeon\Designs (`config.DESIGNS_DIR`, `design.write_file`,
  written on a worker). Renaming renames the file; deleting sends it to the
  Recycle Bin (`design.recycle_file`).
- **Block list** is a list like the sidebar (icon, name, short line), with no
  scrollbar; the wheel still scrolls it. Colour code boxes are as tall as the
  swatch next to them.
- **Formatting like Outlook on My message.** Message, Signature and the new
  Footer tab use `RichBox` (`app/ui/widgets/rich_text.py`) with a pinned toolbar:
  font, size, bold, italic, underline, strikethrough, colour, highlight,
  bullets, numbers, indent, alignment, links, pictures and clear. The editor
  saves tidy email HTML (`document_to_html`), so the spam score is not hurt by
  editor clutter. Pictures go into the email as inline parts (cid:).
- **Footer** (new): small grey print under the signature, such as a company
  address or confidentiality note. Column `template_sets.footer_html` (schema
  5). "Show me an example" fills one in every language.
- **Starting designs** now use headings, bold and bullet points. The "Show me an
  example" messages stay plain so they keep reaching the main inbox.
- **Scrolling.** Scrollbars are thin and widen when the mouse is over them.
  Smooth scrolling (`app/ui/scrolling.py`), with a switch in Settings.
- **Fixes.** Adding a block to a Blank design and removing a warm-up day could
  crash the app (a widget was freed while still in use). Setup guide step
  numbers now line up with their titles.

## v0.7.2 beta

- **Nobody is emailed twice.** New `contacted` table (schema 4), keyed by email
  and campaign, filled from the existing history on upgrade. The Send page now
  always keeps the current campaign; before, a finished campaign made the next
  Send create a new one and queue everyone again, and Clear whole list deleted
  the campaign, so a re-import emailed people a second time. Queueing is one
  indexed SQL statement (`db.queue_contacts`), sending follows the spreadsheet's
  order, and the worker checks the address once more before each email.
- **Campaigns.** "Start a new campaign" on Send emails emails everyone again
  (bounced, unsubscribed and do-not-contact left out). Right-click "Send to this
  person again" on My contacts and Sent emails. Temporary failures are retried
  up to 3 times, then marked failed.
- **My contacts:** Status is now Not sent yet / Sent, no reply / Replied /
  Bounced / Failed / Unsubscribed / Excluded, with a Last sent column and a
  "Show:" filter.
- **Bounce detection.** Inbox checked in the background every 10 minutes while
  the app is open (was: only while My inbox was open, every 30). Bounces matched
  by Message-ID; Outlook, Microsoft 365, Yahoo and Zoho wording; the Junk folder
  is read for bounces; delay notices are no longer bounces; a full mailbox is
  retried; out-of-office replies are no longer counted as replies; a renumbered
  mailbox (UIDVALIDITY) is read again. Late bounces count toward the 5% stop.
- **Email design is drag and drop.** Block tiles with real icons, drag blocks in
  and around with a drop line, type straight onto the email, resize handles for
  pictures, buttons and empty space, a move grip on the toolbar instead of
  arrows, and a simpler right panel ("Look" plus "More options").
- **Setup installs the newest version.** An installer from v0.7.2 on checks
  GitHub first and installs a newer release instead (checked against GitHub's
  SHA-256), or its own copy when offline.
- **Look:** number boxes have proper arrows inside the box, and drop-down lists
  open straight below their box.

## v0.7.1 beta

- **Email design page** (new, between My message and Sending options). A
  Canva-style editor: blocks on the left (heading, text, quote, links row, logo,
  banner, picture, video, button, social icons, two columns, card, line, empty
  space, footer, your own HTML), a live clickable picture of the email in the
  middle, settings for the selected block or the whole email on the right.
  Eight starting designs, undo/redo, computer and phone views, a brand kit
  (logo, colours, font), several saved designs, save to and open from a
  `.hpdesign` file, open in browser and send me a test. The design is a frame:
  the "Your message" block is where each person's mixed message goes, so the
  anti-spam variety still works. Pictures are shrunk and sent inside the email
  as inline parts (cid:). New `app/core/design.py`, `app/ui/pages/design.py`,
  `app/ui/widgets/email_canvas.py`, table `designs` (schema 3).
- **Warm-up plans.** Very safe, Safe (recommended, the new default), Faster (the
  old ramp) and My own plan, with a box per day that three numbers can fill in
  and a warning when a plan grows faster than is safe. Existing users move to
  Safe; pick Faster on Sending options to keep the old speed.
- **My message:** a new subject or message is added at the top, and the
  personal-touch buttons, style buttons and Add button stay pinned at the top
  while the list scrolls (`StickyBar` in `widgets/common.py`).
- Tests: a fixture now deletes each UI test's windows when it ends. Without it
  they piled up and the next test that waited on the event loop crashed Qt
  (this was already true in v0.7.0, just never triggered).

## v0.7.0 beta

- **Five languages.** English, Arabic, German, Spanish and French, chosen in
  Settings → Language (first run follows the computer's language). Every page,
  button, message, dialog and help text is translated; Arabic switches the whole
  app to right to left. The unsubscribe line, name fallbacks, examples and the
  blank spreadsheet follow the language; unsubscribe replies are recognised in
  all five. New `app/i18n/`, `tools/i18n.py`, `tests/test_i18n.py`,
  [languages.md](languages.md).
- **The spam score reads the finished email** for the contact on screen, with
  signature, link and footer, instead of each part on its own, and estimates
  where it lands: main inbox, Promotions or spam, with what to change.
- **Examples rewritten to reach the main inbox**, in every language, and a new
  "Reaching the main inbox, not spam or Promotions" section in the My message
  guide.
- A spreadsheet column that is empty for one contact is now left blank instead
  of being sent as a literal {{Column}}; the score points out blank tags.
- Drop-downs keep English values in code while showing translations (`Combo`).
- Status rows never squash on a short window; the page scrolls instead.

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
