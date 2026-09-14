# 🕊 HomingPigeon

**Safe, simple email for your business.**

Send outreach email to your contact list without landing in the spam folder or getting your
company domain blacklisted.

HomingPigeon does the things that normally go wrong: it checks that your domain is set up
correctly, cleans your contact list before you send, makes every message slightly different,
sends at a human pace, and quietly removes addresses that bounce.

Works on **Windows, Mac and Linux**.

> **Free while in beta (v0.1).** Please report anything confusing or broken.

---

## Getting started (no technical knowledge needed)

You do not need to type any commands.

### 1. Download the app

1. Near the top of this page, click the green **Code** button, then **Download ZIP**.
2. Find the downloaded ZIP file (usually in your **Downloads** folder).
3. **Unzip it** — this step matters, the app will not start from inside the ZIP:
   - **Windows:** right-click the ZIP → **Extract All…** → **Extract**.
   - **Mac:** double-click the ZIP.
   - **Linux:** right-click the ZIP → **Extract Here**.
4. Move the unzipped folder somewhere you will find it again, such as **Documents**.

### 2. Double-click the Start file for your computer

Open the folder. Inside it, double-click the one file that matches your computer:

| Your computer | Double-click this file |
|---|---|
| **Windows** | **`Start HomingPigeon - Windows.bat`** |
| **Mac** | **`Start HomingPigeon - Mac.command`** |
| **Linux** | **`Start HomingPigeon - Linux.sh`** |

> On Windows the `.bat` ending may be hidden, so the file can just show as
> **Start HomingPigeon - Windows**.

### 3. The first time only

The first time, a small window opens and gets everything ready. **Keep it open** and stay
connected to the internet. It takes about **2–5 minutes**, then the app opens by itself.

- **If your computer doesn't have Python** (a free program the app is built with), the window
  offers to install it for you:
  - **Windows:** press **Y**. It installs by itself.
  - **Mac:** press **Return**. The Python installer opens — click **Continue** and **Install**
    (your Mac may ask for your password). Setup carries on when the installer closes.
  - **Linux:** the window shows the one command to install it.
- **From then on**, double-clicking the Start file opens the app straight away.

### If your computer shows a warning

Your computer warns about any new file downloaded from the internet. This is normal.

- **Windows — "Windows protected your PC":** click **More info**, then **Run anyway**.
- **Mac — "cannot be opened" or "Apple could not verify…":** click **Done** (or **OK**), open
  **System Settings → Privacy & Security**, scroll down and click **Open Anyway** next to the
  message about the Start file. On older Macs you can instead **right-click** the file and
  choose **Open**. You only need to do this once.
- **Linux — the file opens in a text editor instead of running:** right-click it →
  **Properties** → **Permissions** → tick **Allow executing file as program**, then
  double-click it again (choose **Run** if asked).

### Using the app

The very first time it opens, everything is empty. Go to the **Setup guide** page inside the app
and follow it from the top — it walks you through every step and ticks them off as you go.

**Everything you type is saved automatically.** Close the app and open it again, and your email
settings, templates and contacts are all still there. You only set it up once.

**Windows tip:** on the **Setup guide** page, click **"Put an icon on my Desktop"**, and from
then on just double-click that icon.

### Updating to a new version

Download the new ZIP, unzip it, and use its Start file. You can delete the old folder.
**Your settings, contacts and templates are kept** — they are stored separately from the app
(see below). If the new version needs anything extra, the Start file fetches it by itself.

---

## Where your information is kept

Your settings, contacts and templates live in a folder separate from the app, so replacing or
deleting the app folder **never touches your data**:

| Computer | Folder |
|---|---|
| Windows | `C:\Users\<your name>\AppData\Roaming\HomingPigeon` |
| Mac | `~/Library/Application Support/HomingPigeon` |
| Linux | `~/.local/share/HomingPigeon` |

Your email password is stored encrypted. On Windows it uses Windows' own protection (DPAPI), so
it can only be read by your Windows account on your computer. It is never sent anywhere.

The parts the app needs to run (downloaded by the Start file) are kept in a separate private
folder — `AppData\Local\HomingPigeon\runtime` on Windows — so they never interfere with any other
program on your computer.

---

## What the app does for you

| What | Why it matters |
|---|---|
| **SPF / DKIM / DMARC checker and generators** | These are settings at your domain provider that prove your email is really from you. Without them, your mail is filtered no matter how good it is. Gmail and Yahoo now require them. |
| **Warm-up ramp** | Starts at about 20 emails a day and increases over several weeks. A brand-new sender suddenly sending hundreds looks like a hacked account. |
| **Several subjects and messages** | The app picks a different combination for each person, so hundreds of identical emails never go out. |
| **Random delay between emails** | You set a minimum and maximum with a slider. A fixed interval is an obvious sign of automation. |
| **Office-hours sending** | Emails arriving at 3am look automated. You can also list public holidays to skip. |
| **Address checking on import** | Dead addresses bounce, and bounces are the fastest way to get blacklisted. |
| **Automatic stop** | Sending halts by itself if too many emails start failing, before real damage is done. |
| **Bounce and unsubscribe handling** | Reads your inbox and permanently removes anyone who bounced or asked to be removed. |
| **Spam score before you send** | Warns you about wording, links and attachments that trigger filters. |
| **One-click unsubscribe** | Adds the standard header that puts an Unsubscribe button in Gmail and Outlook — providers reward this. |

---

## Frequently asked

**Nothing happens / the window closes straight away.**
Make sure you unzipped the download first (step 1.3) and are double-clicking the Start file
inside the unzipped folder. If setup stopped part-way (for example the internet dropped),
double-click the Start file again — it picks up where it left off.

**Do I need a website or a company domain?**
You need an email address on your own domain (like `you@yourcompany.com`). Sending business
outreach from a free Gmail or Hotmail address gets filtered much harder, and you cannot prove
ownership of it.

**My password doesn't work.**
If your email has two-factor authentication (most do), you need an **app password** rather than
your normal one. The app tells you exactly where to get it for your provider — Gmail, Microsoft
365, Zoho and others all have presets.

**How many emails can I send?**
The app starts you at roughly 20 a day and increases gradually. This is deliberate. Sending
more, faster, is how domains get blacklisted — and a blacklisted domain can break your normal
business email too, not just your outreach.

**Can I attach a brochure or document?**
Yes, up to 2 MB — but the app defaults to a *link* instead, because attachments from unknown
senders are one of the strongest spam signals there is.

**Is my contact list uploaded anywhere?**
No. Everything stays on your computer. The app only talks to your own email provider and to
public DNS (to check your domain settings).

---

## For developers

```
Start HomingPigeon - *  double-click launchers (find/install Python, then run tools/launch.py)
tools/launch.py         creates the private runtime, installs requirements.txt, starts run.py
run.py                  app entry point
app/config.py           app name, paths, limits
app/theme.py            colours, fonts, widget factories
app/core/               engine: db, importer, merge, composer, sender, scorer, warmup,
                        imap_sync, dns_tools, exporter, credentials, shortcut, tls
app/ui/                 shell + one module per page
tools/build_exe.py      PyInstaller build (single Windows .exe)
tests/                  pytest suite
```

`requirements.txt` is what the app needs to run (the Start files install it).
`requirements-dev.txt` adds the build and test tools:

```
pip install -r requirements-dev.txt
python run.py
python -m pytest tests/ -q
```

Test sending without emailing anybody real — start a local mail server that accepts and discards
everything:

```
python -m aiosmtpd -n -l localhost:1025
```

Then in the app set the server to `localhost`, port `1025`, security **None (testing only)**.

### Building a single Windows .exe

```
python tools/build_exe.py
```

This produces **`dist\HomingPigeon.exe`** — one file that runs on any Windows PC with no Python
installed. Pushing a tag like `v0.1.0` makes GitHub Actions build it and attach it to the
repository's **Releases** page.

## A note on DKIM

The app can generate a DKIM key pair, but that is **only usable if you run your own mail
server**. On Google Workspace, Microsoft 365, Zoho or normal web hosting, your provider holds
the signing key — so for those the app shows the exact steps to switch it on in their control
panel instead. See **Deliverability → DKIM setup** in the app.

## Licence and responsibility

You are responsible for who you email and for following the law where you and your recipients
live (GDPR, CAN-SPAM, and similar). This tool helps you send responsibly — it does not make
unsolicited email legal. Always honour unsubscribe requests immediately; the app does this
automatically if you let it.
