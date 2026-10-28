# To do later: turn on the "Sign in with Google / Microsoft" buttons

A checklist for the app's owner. **Not needed for v0.8.1 to work.** Until this is
done the buttons stay hidden, and users connect Gmail, Outlook and others with an
app password as before.

When this is done, users press a button, pick their account in the browser and
click Allow. No app passwords.

## What it costs

| Step | Cost |
|---|---|
| Microsoft app registration | Free. No review, no fees |
| Google project, Gmail API, client ID | Free. No billing account needed |
| Users signing in | Free for you and for them |

If either site asks for a credit card, stop: you do not need Azure or Google
billing for this. Ask Claude.

Later, when selling (not needed to start):

- **Google verification**: removes the "Google hasn't verified this app" warning
  and the 100-user limit. Needs a yearly security assessment by an approved lab,
  roughly 500 to a few thousand US dollars a year. Needs your website live first
  (home page, privacy policy, terms).
- **Microsoft publisher verification**: free, with a free Microsoft Partner
  Network ID. Removes "unverified" from Microsoft's sign-in screen.

## Part 1: Microsoft (about 15 minutes)

1. Go to **entra.microsoft.com** and sign in with any Microsoft account.
2. Open **App registrations**, then **New registration**.
   - Name: `HomingPigeon`
   - Supported account types: **Accounts in any organizational directory and
     personal Microsoft accounts**
   - Redirect URI: pick **Public client/native (mobile & desktop)** and type
     `http://localhost`
   - Press **Register**.
3. Copy the **Application (client) ID**. Keep it somewhere safe. (1 of 3)
4. Click **Authentication**. Under Advanced settings set **Allow public client
   flows** to **Yes**. Press Save.
5. Click **API permissions**, then **Add a permission**, then **APIs my
   organization uses**. Search **Office 365 Exchange Online**, pick
   **Delegated permissions**, tick **IMAP.AccessAsUser.All** and **SMTP.Send**,
   then Add.
6. **Add a permission** again, **Microsoft Graph**, **Delegated permissions**:
   make sure **offline_access**, **openid** and **email** are ticked.
7. Do **not** press "Grant admin consent".

## Part 2: Google (about 15 minutes)

1. Go to **console.cloud.google.com**. Use a business Google account if you have
   one: it will own the app when you sell it.
2. Top bar, project picker, **New project**. Name it `HomingPigeon`. Create it
   and make sure it is selected.
3. Menu, **APIs & Services**, **Library**. Search **Gmail API**, press **Enable**.
4. Open **OAuth consent screen** (newer screens call it **Google Auth Platform**),
   press **Get started**:
   - App name `HomingPigeon`, your email as support email.
   - Audience: **External**.
   - Contact email: yours. Agree and create.
5. **Data access** (or **Scopes**): add `https://mail.google.com/`, `openid` and
   `.../auth/userinfo.email`. Save.
6. **Clients** (or **Credentials**): **Create client**, type **Desktop app**,
   name `HomingPigeon desktop`. Create.
7. Copy the **Client ID** (2 of 3) and the **Client secret** (3 of 3).
8. **Audience**: add your own Gmail address (and any testers) as **test users**.
   Do not press Publish yet.
   - While in Testing, only the test users can sign in, and a sign-in lasts 7
     days before it must be repeated. Fine for trying it out.
   - Publish when your website is live and you are ready for Google's review.

## Part 3: hand the three codes to Claude

Open Claude Code in this project and say something like:

> Turn on the sign-in buttons. Microsoft client ID: ...  Google client ID: ...
> Google client secret: ...

**Do not paste them into the code yourself.** The GitHub repo is public, and
GitHub's scanner flags Google client secrets pushed there. Claude will keep them
out of the public code but inside the built app, test signing in with you, and
build the next version.

## Good to know

- Some Microsoft 365 companies require their IT admin to approve a new app once.
  Users see "Need admin approval" and pass it to their IT person.
- Microsoft 365 admins must also allow "Authenticated SMTP" for the mailbox. The
  app already tells users this when it happens.
- The button names on Google's and Microsoft's sites change from time to time.
  If a step does not match, ask Claude. The technical version of these notes is
  in [handover/sign-in-setup.md](handover/sign-in-setup.md).
