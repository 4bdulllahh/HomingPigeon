# Uniformers Mailer

A desktop app for sending business outreach email safely — without getting your domain
spam-foldered or blacklisted.

It does the things a bulk mailer normally leaves to you: checking that your domain is properly
authenticated, cleaning the list before you send, varying every message, pacing sends like a human,
and pulling bounced addresses out automatically.

## Running it

```bash
pip install -r requirements.txt
python run.py
```

To build a single `.exe` for office machines with no Python installed:

```bash
python tools/build_exe.py      # → dist/UniformersMailer.exe
```

Settings, the database and exports live in `%APPDATA%\UniformersMailer\`, so rebuilding or
replacing the executable never touches your data.

## First-time setup

Work through the **Setup guide** page in the app — it ticks each step off automatically. In short:

1. **Email account** — enter your SMTP details. Pick your provider from the presets and press
   *Test connection*; the error messages tell you exactly what to fix.
2. **Deliverability** — enter your domain and run the checks. Fix anything marked red using the
   built-in SPF and DMARC generators, and the per-provider DKIM instructions.
3. **Contacts** — import your spreadsheet. Columns are detected automatically.
4. **Templates** — write 3+ subjects and 2-3 bodies, then check the spam score.
5. **Campaign** — set the brochure link, the delay range and your sending hours.
6. **Send** — the pre-flight list must be green before you start.

## How it protects your domain

| Feature | Why it matters |
|---|---|
| SPF / DKIM / DMARC checker + generators | Unauthenticated mail is filtered regardless of content. Gmail and Yahoo now require DMARC for bulk senders. |
| Warm-up ramp | Starts at ~20/day and rises over weeks. A new sender suddenly emitting hundreds of emails looks compromised. |
| Subject + body variants and spintax | Identical messages in volume are trivial to fingerprint. Every recipient gets a different combination. |
| Randomised delay (min–max slider) | A fixed interval is a bot signature. |
| Business-hours window | Bulk mail at 3am is an automation signal. |
| MX validation on import | Dead domains bounce, and bounces are the fastest route to a blacklist. |
| Bounce circuit breaker | Sending stops automatically above a 5% hard-bounce rate or 5 consecutive failures. |
| IMAP bounce & unsubscribe sync | Bounced and opted-out addresses are suppressed permanently. |
| Plain-text alternative on every message | HTML-only mail scores badly everywhere. |
| `List-Unsubscribe` header | Gives the native Unsubscribe button in Gmail and Outlook, which providers reward. |
| No `X-Mailer` header | Bulk tools that announce themselves in the headers get filtered. |
| Link the brochure instead of attaching | Attachments from unknown senders raise spam scores sharply. |

## Testing without sending real email

Run a local SMTP server that accepts and discards everything:

```bash
python -m aiosmtpd -n -l localhost:1025
```

Then set host `localhost`, port `1025`, security *None (testing only)* on the Email account page.

Run the test suite with:

```bash
python -m pytest tests/ -q
```

## A note on DKIM

The app can generate a DKIM key pair, but that is **only usable if you run your own mail server**
(Postfix/OpenDKIM and similar). On Google Workspace, Microsoft 365, Zoho or shared hosting, the
provider holds the signing key — so for those the app shows the exact click-path in their admin
console instead. Deliverability → DKIM setup.

## Project layout

```
run.py                  launcher
app/config.py           paths and limits
app/theme.py            VS Code-style tokens and widget factories
app/core/               engine: db, importer, merge, composer, sender,
                        scorer, warmup, imap_sync, dns_tools, exporter,
                        credentials
app/ui/                 shell + one module per page
tools/build_exe.py      PyInstaller build
tests/                  pytest suite
```

`Email Sender.py` is the original single-file script this replaced, kept for reference.
