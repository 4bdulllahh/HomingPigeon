# 🕊 HomingPigeon

**Safe, simple email for your business.**

Send outreach email to your contact list without landing in the spam folder or getting your
company domain blacklisted.

HomingPigeon does the things that normally go wrong: it checks that your domain is set up
correctly, cleans your contact list before you send, makes every message slightly different,
sends at a human pace, and quietly removes addresses that bounce.

> **Free while in beta (v0.1).** Please report anything confusing or broken.

---

## Getting started — the easy way (no technical knowledge needed)

**You do not need to install Python or use any commands.**

1. Go to the **[Releases](../../releases)** page of this repository.
2. Download **`HomingPigeon.exe`**.
3. Put it somewhere you will find it again — your **Desktop** or **Documents** folder is perfect.
4. **Double-click it.** That's it.

> **"Windows protected your PC"?**
> Windows shows this warning for any new program that it has not seen before. Click
> **More info**, then **Run anyway**. This happens because the app is not yet code-signed
> (a certificate costs several hundred dollars a year); it is not a sign that anything is wrong.

The very first time it opens, everything is empty. Go to the **Setup guide** page inside the app
and follow it from the top — it walks you through every step and ticks them off as you go.

**Everything you type is saved automatically.** Close the app and open it again, and your email
settings, templates and contacts are all still there. You only set it up once.

---

## Getting started — from the source code

Only needed if you want to change the code or build the app yourself.

### Step 1 — Install Python

Download it from [python.org/downloads](https://www.python.org/downloads/).
**Important:** on the first screen of the installer, tick the box that says
**"Add python.exe to PATH"** before clicking Install.

### Step 2 — Open the black command window

1. Hold the **Windows key** (the one with the Windows logo, between Ctrl and Alt) and press **R**.
   A small "Run" box appears in the corner of your screen.
2. Type **`cmd`** and press **Enter**.
3. A black window opens. This is where you type the commands below.

### Step 3 — Copy the app onto your computer

Type each line below and press **Enter** after each one:

```
cd %USERPROFILE%\Documents
git clone https://github.com/YOUR-USERNAME/HomingPigeon.git
cd HomingPigeon
```

This puts the app in your **Documents** folder, in a folder called **HomingPigeon**.

> **"git is not recognised"?** You don't have Git. Either install it from
> [git-scm.com](https://git-scm.com/download/win), or skip Git entirely: click the green
> **Code** button at the top of this page, choose **Download ZIP**, and unzip it into your
> Documents folder.

### Step 4 — Install the parts it needs

```
pip install -r requirements.txt
```

Wait for it to finish — it downloads a few things and takes a minute or two.

### Step 5 — Start the app

```
python run.py
```

The app window opens.

### Opening it again later

You do **not** have to repeat all of that. Inside the app, open the **Setup guide** page and
click **"Put an icon on my Desktop"**. From then on, just double-click that icon.

Or, to start it manually: open your **Documents → HomingPigeon** folder, click the address bar
at the top of the window, type `cmd`, press Enter, then type `python run.py`.

### Building the single .exe yourself

```
python tools/build_exe.py
```

This produces **`dist\HomingPigeon.exe`** — one single file, about 77 MB, that runs on any
Windows PC with no Python installed. Copy it anywhere you like.

---

## Where your information is kept

Your settings, contacts and templates live in a folder separate from the app:

```
C:\Users\<your name>\AppData\Roaming\HomingPigeon
```

This means you can safely replace the app or the `.exe` with a newer version — **your data is
never touched.** Your email password is encrypted there using Windows' own protection (DPAPI),
so it can only be read by your Windows account on your computer. It is never sent anywhere.

---

## What the app does for you

| What | Why it matters |
|---|---|
| **SPF / DKIM / DMARC checker and generators** | These are settings at your domain provider that prove your email is really from you. Without them, your mail is filtered no matter how good it is. Gmail and Yahoo now require them. |
| **Warm-up ramp** | Starts at about 20 emails a day and increases over several weeks. A brand-new sender suddenly sending hundreds looks like a hacked account. |
| **Several subjects and messages** | The app picks a different combination for each person, so hundreds of identical emails never go out. |
| **Random delay between emails** | You set a minimum and maximum with a slider. A fixed interval is an obvious sign of automation. |
| **Office-hours sending** | Emails arriving at 3am look automated. |
| **Address checking on import** | Dead addresses bounce, and bounces are the fastest way to get blacklisted. |
| **Automatic stop** | Sending halts by itself if too many emails start failing, before real damage is done. |
| **Bounce and unsubscribe handling** | Reads your inbox and permanently removes anyone who bounced or asked to be removed. |
| **Spam score before you send** | Warns you about wording, links and attachments that trigger filters. |
| **One-click unsubscribe** | Adds the standard header that puts an Unsubscribe button in Gmail and Outlook — providers reward this. |

---

## Frequently asked

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

**Can I attach my brochure?**
Yes, up to 2 MB — but the app defaults to a *link* instead, because attachments from unknown
senders are one of the strongest spam signals there is.

**Is my contact list uploaded anywhere?**
No. Everything stays on your computer. The app only talks to your own email provider and to
public DNS (to check your domain settings).

---

## For developers

```
run.py                  launcher
app/config.py           app name, paths, limits
app/theme.py            colours, fonts, widget factories
app/core/               engine: db, importer, merge, composer, sender, scorer,
                        warmup, imap_sync, dns_tools, exporter, credentials, shortcut
app/ui/                 shell + one module per page
tools/build_exe.py      PyInstaller build
tests/                  pytest suite
```

Run the tests:

```
python -m pytest tests/ -q
```

Test sending without emailing anybody real — start a local mail server that accepts and discards
everything:

```
python -m aiosmtpd -n -l localhost:1025
```

Then in the app set the server to `localhost`, port `1025`, security **None (testing only)**.

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
