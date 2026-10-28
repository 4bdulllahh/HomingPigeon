# Roadmap: features planned but not built yet

Claude reads this before each new batch of changes or release and asks whether to
include any open item. When one is built, move it to "Done" with the version.

## Open

### For users

- **Follow-ups.** A short automatic nudge a few days later to people who did not
  reply (or who opened but did not reply, now that delivery reports exist). The
  biggest win for cold outreach. Must respect the do-not-email list, the warm-up
  cap and "never email someone twice" (a follow-up is a planned second email,
  not a repeat of the first).
- **Reply from the app.** Answer a reply from My inbox without opening Gmail.
- **Scheduled campaigns.** Pick a start date and time for a campaign.
- **Multiple senders (paid tiers).** Standard: one sending address. Pro: 5.
  Enterprise: 15 to 20. Warm-up, daily limits and the bounce brake become per
  address. Sign-ins are already stored per slot (`app/core/oauth.py`), which
  helps.
- More will come from beta testers' feedback: add it here.

### For selling the app

- **Accounts and subscriptions.** The app is downloaded from the maker's
  website, where people sign up, log in and buy a subscription. The app then asks
  them to log in with that same website account and only works while the
  subscription is active. Needs: the website's login and payments, a small
  licence check in the app (with a grace period when offline), and a plan for
  which tier unlocks what (see Multiple senders).
- **Google verification** for "Sign in with Google": needs the website live
  (home page, privacy policy, terms, domain verified in Google Search Console),
  then the yearly security assessment. Until then: 100 users, warning screen.
- **Microsoft publisher verification**: free with a Microsoft Partner Network
  ID, removes "unverified" from the Microsoft sign-in screen.
- **Code signing** for Setup.exe, so Windows Smart App Control and SmartScreen
  stop blocking it.

### Known limits to remember

- Opens are approximate everywhere: Apple Mail and some company filters open
  emails automatically. Replies are the number to trust.
- SendGrid shares opens and clicks only with its paid Email Activity add-on.
  Postmark reports opens, clicks and bounces but not deliveries.

## Done

- v0.8.1: delivery reports, separate inbox login, Google and Microsoft sign-in
  (buttons hidden until the app IDs are added), campaign results, contact history.
