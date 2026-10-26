<p align="center">
  <img src="assets/logo-256.png" width="160" alt="HomingPigeon logo: a pigeon in a flight cap and goggles, carrying a backpack of letters">
</p>

<h1 align="center">HomingPigeon</h1>

<p align="center"><b>Safe, simple email for your business.</b></p>

<p align="center">
  <a href="../../releases/latest"><b>Download</b></a> ·
  Version 0.8.0 (free beta) · Windows, Mac and Linux ·
  English, العربية, Deutsch, Español, Français
</p>

Send outreach email to your contact list without landing in the spam folder or getting your
company domain blacklisted.

HomingPigeon does the things that normally go wrong: it checks that your domain is set up
correctly, cleans your contact list before you send, makes every message slightly different,
sends at a human pace, and quietly removes addresses that bounce. It runs on your own computer,
and your contacts never leave it.

![The HomingPigeon home page: emails sent today, sendable contacts, replies and bounce rate, sending health checks, the current campaign and recent activity](docs/screenshots/home.png)

> **Free while in beta.** Please [report anything confusing or broken](../../issues/new).

## New in 0.8

- **Themes.** Pick one of eight ready-made themes or make your own: your colours, a gradient
  and a font. Save it to a file to share it.
- **Your menu, your order.** Drag the pages on the left into any order and hide the ones you
  never use.
- **Filter by date** on Sent emails, My inbox and My contacts.
- **See your email on a phone** and **send yourself a test** straight from My message.
- **Undo an import** of subjects or messages with one click.

The full history is in [`docs/handover/changelog.md`](docs/handover/changelog.md).

## Features

### Before you send

- **A setup guide that ticks itself off.** The **Start here** page walks you through every
  step in plain English and marks each one done from the real state of the app, so you always
  know what is left.
- **Domain check, with SPF, DKIM and DMARC generators.** These settings at your domain
  provider prove your email is really from you. Without them your mail is filtered no matter
  how good it is, and Gmail and Yahoo now require them. The app checks yours and writes the
  records for you.
- **Contact list cleaning on import.** Open an Excel or CSV file and the app finds the email,
  company and contact columns by itself, then removes duplicates, invalid addresses and
  domains with no mail server. Every other column in your sheet is kept and can be used in
  your message as a tag, such as `{{Phone No.}}`.
- **Spam score before you send.** A live preview shows exactly what one contact will
  receive, and the score reads that finished email: subject, message, link, signature and
  footer together. You get a score out of 100, an estimate of whether it lands in the main
  inbox, Gmail's Promotions tab or spam, and plain-English advice on what to change.

### Writing your email

- **Several subjects and messages.** Write a few versions of each, use tags like
  `{{FirstName}}` and `{{Company}}`, and the app picks a different combination for each
  person, so hundreds of identical emails never go out.
- **Formatting like Outlook.** Fonts, sizes, colours, bold, italic, bullet points, numbered
  lists and links. Your signature can carry your logo, and a **Footer** adds small print such
  as your company address. Paste from Word or Outlook and the formatting comes with it,
  cleaned up so it does not hurt your spam score.
- **Import and export.** Bring subjects, messages, signatures and footers in from a
  spreadsheet, check each one, and add the ones you want. Export them to give to someone else.
- **Email designs, as easy as Canva.** Start from a blank page or a ready-made design
  (simple letter, announcement, welcome card, newsletter, event invitation and more), drag
  blocks in, type straight onto the email and drag pictures to resize them. Add logos,
  banners, buttons, social icons and columns, keep a brand kit, and check the phone view.
  Plain emails stay the default, because they reach the main inbox best on first contact.
- **Examples that reach the main inbox.** Press **Show me an example** for subjects and
  messages written the way personal emails are.

### While it sends

- **A warm-up plan you choose.** Very safe, Safe (recommended) or Faster, or type your own
  number for each day. A brand-new sender suddenly sending hundreds looks like a hacked
  account.
- **Human pacing.** A random delay between emails, office hours only, weekdays only and
  public holidays skipped. A fixed interval at 3am is an obvious sign of automation.
- **Nobody gets the same email twice.** Each person is remembered by their address, so
  stopping and starting, clearing the list or importing the same sheet again never sends a
  second copy. To email everyone again with a new message, press **Start a new campaign**.
- **An automatic stop.** Sending halts by itself if too many emails fail or bounce, before
  real damage is done to your domain.

### After it sends

- **Bounce and unsubscribe handling.** The app checks your inbox every 10 minutes while it is
  open, including Junk, and permanently removes anyone who bounced or asked to be removed.
  Out-of-office replies and "still trying" notices are not mistaken for bounces.
- **An inbox you can read.** **My inbox** keeps every reply, bounce and opt-out so you can open
  them inside the app.
- **A record of everything sent.** **Sent emails** keeps every message with the time, the
  subject used and what came back. Double-click one to see it exactly as it went out, or
  export the lot to Excel.

### Comfort

- **In your language.** English, Arabic, German, Spanish or French. Arabic turns the whole app
  to read from right to left.
- **Make it yours.** Dark, light, match your computer, eight more themes, or your own.
- **Easy to read.** Five text sizes, high contrast, bold text and smooth scrolling.
- **Updates itself** and keeps your data. **Backups** save everything to one file you can
  restore on this computer or a new one.

## Screenshots

| | |
|---|---|
| ![The My message page previewing one personalised email next to its spam score of 97 and the estimate that it will land in the main inbox](docs/screenshots/spam-score.png) | ![The Email design page: blocks to drag in on the left, a designed email in the middle with the photo selected, and the photo's settings on the right](docs/screenshots/design.png) |
| **Spam score.** The finished email for a real contact, and where it will land. | **Email design.** Drag blocks in, type straight onto the email, resize pictures. |
| ![The My contacts page listing imported contacts with company, person, status, last sent date and source file](docs/screenshots/contacts.png) | ![The Send emails page with its before-you-send checklist, counters and the Start Emailing button](docs/screenshots/send.png) |
| **My contacts.** Each person's status and when they were last emailed. | **Send emails.** A checklist first, then sending you can pause any time. |
| ![The warm-up section of Sending options with office hours, weekdays only, and the Very safe, Safe, Faster and My own plan choices](docs/screenshots/warmup.png) | ![The Settings page in the Midnight theme with a gradient sidebar, showing the theme choices and Make my own theme](docs/screenshots/themes.png) |
| **Warm-up and timing.** A safe daily plan and office hours only. | **Themes.** Pick one or make your own and share it as a file. |

![The home page in Arabic, with the whole layout mirrored to read from right to left](docs/screenshots/home-arabic.png)
**In your language.** English, Arabic, German, Spanish or French; Arabic mirrors the whole app.

## Install on Windows

You don't need to know anything about coding.

1. Go to the **[Releases](../../releases/latest)** page and download **`HomingPigeon-v0.8.0.zip`**.
2. Right-click the downloaded file, choose **Extract All...** and then **Extract**.
3. In the folder that opens, double-click **`HomingPigeon Setup.exe`**.
4. Click **Install**. Setup downloads what the app needs (about 170 MB), checks it is genuine
   and sets everything up, usually in about a minute.
5. Choose whether to add HomingPigeon to the **Start menu** and the **Desktop**, then click
   **Finish**.

No administrator password is needed, and nothing else on your computer is changed.

**If Windows shows a warning:**

- **"Windows protected your PC"**: click **More info**, then **Run anyway**.
- **"Smart App Control blocked an app that may be unsafe"** (some Windows 11 PCs): use the
  backup installer in the same folder. Right-click
  **`Install HomingPigeon (if Setup is blocked).bat`**, choose **Properties**, tick **Unblock**
  at the bottom, click **OK**, then double-click it. It opens exactly the same Setup window.
  Tip: tick **Unblock** on the downloaded `.zip` before you extract it, and nothing inside needs
  unblocking afterwards.

**Updating** is automatic. When a new version is out, a popup appears as you open the app:
click **Update now** and it installs the update and opens again by itself. You can also check
any time in **Settings, Updates and help**.

**Removing:** Windows Settings, Apps, Installed apps, HomingPigeon, Uninstall, or
**Settings, Uninstall HomingPigeon** inside the app. Your information is kept unless you choose
to delete it too.

## Install on Mac or Linux

1. On the **[Releases](../../releases/latest)** page, download **Source code (zip)** and unzip it.
2. Double-click **`Start HomingPigeon - Mac.command`** (Mac) or
   **`Start HomingPigeon - Linux.sh`** (Linux).

The first time, a window gets everything ready (2 to 5 minutes). Keep it open and stay online;
the app opens by itself when it's done. After that, the Start file opens the app straight away.

- **Mac, "cannot be opened":** open **System Settings, Privacy & Security** and click
  **Open Anyway** next to the message about the Start file.
- **Linux, the file opens in a text editor:** right-click it, **Properties**, **Permissions**,
  tick **Allow executing file as program**, then double-click it again.

## Using the app

The first time it opens, everything is empty. Go to **Start here** and follow it from the top;
it ticks each step off as you go.

**Staying out of spam.** On **My message**, press **? How to write your email** for a short
guide, or **Show me an example** to start from a message already written that way.
**Preview & score** tells you where each email is likely to land.

**Everything you type is saved automatically.** Close the app and open it again, and your
settings, messages and contacts are all still there.

## Where your information is kept

Your data lives in a folder separate from the app, so updating or removing the app never
touches it:

| Computer | Folder |
|---|---|
| Windows | `C:\Users\<your name>\AppData\Roaming\HomingPigeon` |
| Mac | `~/Library/Application Support/HomingPigeon` |
| Linux | `~/.local/share/HomingPigeon` |

Your email password is stored encrypted (on Windows with Windows' own protection, so only your
account on your computer can read it). It is never sent anywhere.

## Frequently asked

**Do I need a company domain?**
Yes, an address like `you@yourcompany.com`. Business outreach from a free Gmail or Hotmail
address gets filtered much harder.

**My password doesn't work.**
If your email has two-step sign-in (most do), you need an **app password** instead of your
normal one. The app shows where to get it for Gmail, Microsoft 365, Zoho and others.

**How many emails can I send?**
You start at about 20 a day and it grows gradually. Sending more, faster, is how domains get
blacklisted, and that can break your normal business email too.

**Can I attach a brochure?**
Yes, up to 2 MB, but a link is the default, because attachments from unknown senders are one
of the strongest spam signals.

**Is my contact list uploaded anywhere?**
No. The app only talks to your own email provider and to public DNS to check your domain.

**What about DKIM?**
The app can generate a DKIM key, but that only helps if you run your own mail server. On Google
Workspace, Microsoft 365, Zoho or normal web hosting, your provider holds the key, so the app
shows the steps to switch it on in their control panel instead.

## For developers

The interface is PyQt6, split so the parts that can block never share a thread with the parts
that draw. Start with [`docs/handover/README.md`](docs/handover/README.md): it explains how the
pieces fit, the rules that must not be broken and where each feature lives.

```
run.py            entry point
app/core/         business rules, no UI imports, unit tested
app/workers/      everything slow (SMTP, IMAP, DNS, spreadsheets, scoring)
app/models/       table models, paged from SQLite
app/services/     backup, restore and updates
app/ui/           theme, main window, pages and shared widgets
installer/        the Windows installer
tools/            release build, icons, screenshots, translations
tests/            pytest suite
```

```
pip install -r requirements-dev.txt
python run.py                       # run the app
python -m pytest tests/ -q          # all tests, headless
python tools/take_screenshots.py    # these screenshots, from made-up data
python tools/build_installer.py     # dist/HomingPigeon-vX.Y.Z.zip
```

**Test sending without emailing anyone real:** run `python -m aiosmtpd -n -l localhost:1025`,
then in the app set the server to `localhost`, port `1025`, security **None (testing only)**.

**Making a release:** change `APP_VERSION` in `app/config.py`, commit and push. On GitHub,
draft a new release with a new tag such as `v0.8.1` and publish it. GitHub Actions builds the
zip and attaches it in about 5 minutes, and installed copies offer the update the next time
they open.

## Licence and responsibility

You are responsible for who you email and for following the law where you and your recipients
live (GDPR, CAN-SPAM and similar). This tool helps you send responsibly. It does not make
unsolicited email legal. Always honour unsubscribe requests; the app does this automatically
if you let it.
