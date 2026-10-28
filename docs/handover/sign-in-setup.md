# Sign in with Google and Microsoft: one-time setup

The "Sign in with Google" and "Sign in with Microsoft" buttons on My email
account only appear once HomingPigeon has its own app IDs from each company.
This is done **once, by the app's maker**. Users never see any of it: they press
the button, pick their account in the browser and click Allow.

The IDs go in `app/config.py`:

```python
GOOGLE_CLIENT_ID = ""
GOOGLE_CLIENT_SECRET = ""
MICROSOFT_CLIENT_ID = ""
```

A blank ID hides that button, so a release without them still works: users type
an app password instead. The code is `app/core/oauth.py`.

## Google (about 15 minutes)

1. Go to https://console.cloud.google.com and sign in with the Google account
   that should own HomingPigeon (ideally a business account, not a personal one).
2. Top bar, project picker, **New project**. Name it `HomingPigeon`, then Create
   and select it.
3. Menu, **APIs & Services**, **Library**. Search for **Gmail API** and press
   Enable.
4. **APIs & Services**, **OAuth consent screen** (called "Google Auth Platform"
   in newer consoles). Press Get started:
   - App name `HomingPigeon`, your support email.
   - Audience: **External**.
   - Contact email: yours. Agree and Create.
5. **Data access** (or Scopes): Add or remove scopes, tick
   `https://mail.google.com/`, plus `openid` and `.../auth/userinfo.email`. Save.
6. **Clients** (or Credentials), **Create client**, type **Desktop app**, name
   `HomingPigeon desktop`. Create.
7. Copy the **Client ID** into `GOOGLE_CLIENT_ID` and the **Client secret** into
   `GOOGLE_CLIENT_SECRET`. Google says a desktop app's secret is not treated as
   secret, so it is fine inside the app.
8. **Audience**, **Publish app** (moves it from Testing to In production).
   Stay in Testing only while trying it yourself: in Testing, sign-ins expire
   after 7 days and only the test users you list can sign in.

### What users will see until Google verifies the app

`https://mail.google.com/` is a "restricted" scope. Until Google verifies the
app, users get a **"Google hasn't verified this app"** screen. They press
**Advanced**, then **Go to HomingPigeon (unsafe)**, and it works. Unverified
apps are limited to **100 users** in total.

To remove the warning and the limit, submit the app for verification from the
same page. For this scope Google requires a yearly security assessment (CASA)
by an approved lab, which costs money (roughly a few hundred to a few thousand
US dollars a year). Worth doing once the paid version has users. Until then,
Gmail users can keep using app passwords, which need no verification.

## Microsoft (about 15 minutes, free, no review)

1. Go to https://entra.microsoft.com (or https://portal.azure.com, then
   **Microsoft Entra ID**). Any Microsoft account works; a free one is fine.
2. **App registrations**, **New registration**:
   - Name `HomingPigeon`.
   - Supported account types: **Accounts in any organizational directory and
     personal Microsoft accounts** (the multitenant plus personal option).
   - Redirect URI: platform **Public client/native (mobile & desktop)**, value
     `http://localhost`.
   - Register.
3. Copy the **Application (client) ID** into `MICROSOFT_CLIENT_ID`. There is no
   secret for a desktop app.
4. **Authentication**: under Advanced settings set **Allow public client flows**
   to Yes. Save.
5. **API permissions**, **Add a permission**, **APIs my organization uses**,
   search `Office 365 Exchange Online`, Delegated permissions:
   tick `IMAP.AccessAsUser.All` and `SMTP.Send`. Also make sure Microsoft Graph
   `offline_access`, `openid` and `email` are listed (add them under Microsoft
   Graph, Delegated, if not). Do **not** press "Grant admin consent".
6. Optional but recommended later: **Branding & properties**, add a publisher
   domain and become a verified publisher (needs a free Microsoft Partner
   Network ID). Without it, users see "unverified" on the consent screen, and
   some company IT departments block unverified apps until an admin approves
   them once.

### Things Microsoft 365 users may still hit

- Their administrator must allow **Authenticated SMTP** for the mailbox, even
  with sign-in. The app's error message already says so.
- Some companies require an admin to approve new apps. The user sees "Need admin
  approval"; their IT person approves HomingPigeon once for the whole company.

## Testing it

1. Put the IDs in `app/config.py` and run `python run.py`.
2. My email account: the buttons appear under Outgoing mail and Incoming mail.
3. Sign in, then press Test connection and Test IMAP.
4. Build a release as usual (`python tools/build_installer.py`). The IDs travel
   inside the app.
