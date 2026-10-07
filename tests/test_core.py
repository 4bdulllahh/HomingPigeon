"""Tests for the parts where a silent bug would send wrong mail to real people."""
from __future__ import annotations

import os
import random
import tempfile

import pandas as pd
import pytest

from app.core import composer, db, dns_tools, importer, merge, scorer


@pytest.fixture(scope="module", autouse=True)
def temp_db():
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    db.init(path)
    yield
    db.close()


# --- name cleanup -----------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("H.E. Khalaf Al Habtoor", "Khalaf"),
    ("H.E. Dr. Ahmed Bin Said", "Ahmed"),
    ("Dr. Sarah Jones", "Sarah"),
    ("Eng. Mohammed", "Mohammed"),
    ("pushkar gokhale", "Pushkar"),
    ("WALID MUHAMED", "Walid"),
    ("Ahmed, CEO", "Ahmed"),
    ("McBride Smith", "McBride"),
    ("", "there"),
    (None, "there"),
    ("A. Smith", "there"),
    ("nan", "there"),
])
def test_clean_first_name(raw, expected):
    assert merge.clean_first_name(raw) == expected


def test_clean_company_falls_back():
    assert merge.clean_company("") == "your company"
    assert merge.clean_company("nan") == "your company"
    assert merge.clean_company("  Acme LLC  ") == "Acme LLC"


# --- spintax ----------------------------------------------------------------
def test_spintax_picks_one_option():
    for seed in range(20):
        out = merge.expand_spintax("{Hi|Hello|Hey} there", random.Random(seed))
        assert out in ("Hi there", "Hello there", "Hey there")


def test_spintax_nested():
    out = merge.expand_spintax("{a {b|c} d|e}", random.Random(1))
    assert out in ("a b d", "a c d", "e")


def test_spintax_does_not_eat_merge_tags():
    """Regression: {{Company}} must survive spintax expansion intact."""
    out = merge.expand_spintax("{Hi|Hello} {{Company}}", random.Random(0))
    assert "{{Company}}" in out


def test_render_resolves_tags_alongside_spintax():
    context = merge.build_context({
        "email": "a@b.com", "person": "Mr. Ahmed Khan", "company": "Acme LLC"})
    out = merge.render("{Hi|Hello} {{FirstName}} at {{Company}}", context, rng=random.Random(0))
    assert "Ahmed" in out and "Acme LLC" in out
    assert "{{" not in out


def test_tags_inside_spintax_options():
    context = merge.build_context({"email": "a@b.com", "person": "Ahmed", "company": "Acme"})
    out = merge.render("{Hi {{FirstName}}|Hello {{FirstName}}}", context, rng=random.Random(3))
    assert out in ("Hi Ahmed", "Hello Ahmed")


def test_unbalanced_spintax_detected():
    assert merge.validate_spintax("{Hi|Hello") is not None
    assert merge.validate_spintax("Hi}") is not None
    assert merge.validate_spintax("{Hi|Hello} {{Tag}}") is None


def test_unresolved_tags_reported():
    assert merge.unresolved_tags("{{Compny}} and {{FirstName}}") == ["Compny"]
    assert merge.unresolved_tags("{{Company}}") == []


def test_extra_columns_become_tags():
    context = merge.build_context({
        "email": "a@b.com", "person": "Ahmed", "company": "Acme",
        "extra_json": '{"City": "Lisbon"}'})
    assert context["City"] == "Lisbon"


def test_variant_cycler_avoids_immediate_repeats():
    cycler = merge.VariantCycler(["a", "b", "c"], seed=1)
    picks = [cycler.next() for _ in range(30)]
    assert not any(picks[i] == picks[i + 1] for i in range(len(picks) - 1))


# --- importer ---------------------------------------------------------------
def test_detect_columns_on_real_layout():
    df = pd.DataFrame({
        "NAME OF THE COMPANY": ["Acme"], "EMAIL": ["a@b.com"], "CONTACT PERSON": ["Ahmed"]})
    mapping = importer.detect_columns(df)
    assert mapping.email == "EMAIL"
    assert mapping.company == "NAME OF THE COMPANY"
    assert mapping.person == "CONTACT PERSON"


def test_detect_columns_by_content_when_headers_are_unhelpful():
    df = pd.DataFrame({"col1": ["Acme Ltd"], "col2": ["a@b.com"], "col3": ["Ahmed"]})
    assert importer.detect_columns(df).email == "col2"


def test_detect_columns_alternative_names():
    df = pd.DataFrame({"Organisation": ["Acme"], "E-Mail": ["a@b.com"], "Full Name": ["Ahmed"]})
    mapping = importer.detect_columns(df)
    assert mapping.email == "E-Mail"
    assert mapping.company == "Organisation"


@pytest.mark.parametrize("email,valid", [
    ("a@b.com", True),
    ("first.last+tag@sub.domain.co.uk", True),
    ("no-at-sign", False),
    ("two@@at.com", False),
    ("spaces in@mail.com", False),
    ("a@gmial.com", False),      # typo domain
    ("", False),
])
def test_validate_email(email, valid):
    assert importer.validate_email(email)[0] is valid


def test_role_accounts_flagged():
    assert "role-account" in importer.risk_flags("info@company.com")
    assert importer.risk_flags("ahmed@company.com") == []


def test_import_deduplicates_and_keeps_extras():
    df = pd.DataFrame({
        "EMAIL": ["dup@example.com", "DUP@example.com", "other@example.com"],
        "NAME OF THE COMPANY": ["Acme", "Acme", "Beta"],
        "CONTACT PERSON": ["Ahmed", "Ahmed", "Sara"],
        "City": ["Lisbon", "Lisbon", "Porto"],
    })
    mapping = importer.detect_columns(df)
    result = importer.import_dataframe(df, mapping, source_file="t.xlsx", check_mx=False)
    assert result.duplicates == 1
    assert result.imported == 2
    assert "City" in importer.merge_tag_names()


def test_suppressed_addresses_are_not_imported():
    db.suppress("blocked@example.com", "test")
    df = pd.DataFrame({"EMAIL": ["blocked@example.com"], "NAME OF THE COMPANY": ["X"]})
    result = importer.import_dataframe(df, importer.detect_columns(df), check_mx=False)
    assert result.suppressed == 1
    assert result.imported == 0


# --- composer ---------------------------------------------------------------
def _content(**overrides) -> composer.Content:
    base = dict(
        subject_variants=["Office furniture for {{Company}}"],
        body_variants=["<p>Hi {{FirstName}},</p><p>We make office furniture and would "
                       "like to discuss your team's requirements at {{Company}}. We handle design, "
                       "material selection, bulk production and local delivery across the region.</p>"],
        signature_html="<p>Sam Taylor<br>+1 555 010 0000</p>",
        attach_mode="link", link_url="https://example.com/b.pdf",
    )
    base.update(overrides)
    return composer.Content(**base)


def test_message_is_multipart_with_text_and_html():
    identity = composer.SenderIdentity("Sam Taylor", "sam@example.com", "sam@example.com")
    context = merge.build_context({"email": "x@y.com", "person": "Ahmed", "company": "Acme"})
    message, subject, _ = composer.build_message(identity, "x@y.com", context, _content())

    types = [p.get_content_type() for p in message.walk()]
    assert "text/plain" in types and "text/html" in types
    assert subject == "Office furniture for Acme"
    assert message["List-Unsubscribe"].startswith("<mailto:")
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "X-Mailer" not in message
    assert "@example.com>" in message["Message-ID"]


def test_no_literal_merge_tags_survive():
    identity = composer.SenderIdentity("A", "sam@example.com")
    context = merge.build_context({"email": "x@y.com", "person": "Ahmed", "company": "Acme"})
    message, subject, _ = composer.build_message(identity, "x@y.com", context, _content())
    body = message.get_body(preferencelist=("html",)).get_content()
    assert "{{" not in body and "{{" not in subject


def test_attachment_over_limit_is_rejected(tmp_path):
    from app import config

    big = tmp_path / "big.pdf"
    big.write_bytes(b"0" * (config.MAX_ATTACHMENT_BYTES + 1))
    with pytest.raises(composer.AttachmentTooLarge):
        composer.check_attachment(big)


def test_html_to_text_keeps_links_and_lists():
    text = composer.html_to_text(
        '<p>Hi</p><ul><li>One</li><li>Two</li></ul><a href="https://x.com">Site</a>')
    assert "One" in text and "Two" in text
    assert "Site (https://x.com)" in text
    assert "<" not in text


def test_brochure_link_appears_in_body():
    identity = composer.SenderIdentity("A", "sam@example.com")
    context = merge.build_context({"email": "x@y.com", "person": "A", "company": "B"})
    message, _, _ = composer.build_message(identity, "x@y.com", context, _content())
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "https://example.com/b.pdf" in html


# --- scorer -----------------------------------------------------------------
def test_clean_content_scores_well():
    report = scorer.score(_content(), sender_email="sam@example.com",
                          reply_to="sam@example.com")
    assert report.score >= 70, [f.message for f in report.findings]


def test_spammy_content_scores_badly():
    spam = _content(
        subject_variants=["!!! FREE OFFER ACT NOW LIMITED TIME !!!"],
        body_variants=['<p>CLICK HERE 100% FREE guaranteed! <a href="http://bit.ly/x">buy now</a> '
                       'Make money fast, no risk, offer expires!</p>'])
    report = scorer.score(spam, sender_email="someone@gmail.com", reply_to="other@yahoo.com")
    assert report.score < 50
    categories = {f.category for f in report.findings}
    assert "Subject" in categories and "Identity" in categories


def test_scorer_flags_unresolved_tags_as_critical():
    broken = _content(body_variants=["<p>Hi {{Compny}}, we make office furniture for your team and would "
                                     "welcome a conversation about your requirements this year.</p>"])
    report = scorer.score(broken, sender_email="sam@example.com")
    assert any(f.severity == "critical" and f.category == "Merge tags" for f in report.findings)


def test_scorer_does_not_complain_about_auto_footer():
    report = scorer.score(_content(unsubscribe_note=True), sender_email="sam@example.com")
    assert not any(f.message == "No unsubscribe wording anywhere in the email."
                   for f in report.findings)


def test_scorer_flags_missing_footer_when_disabled():
    report = scorer.score(_content(unsubscribe_note=False), sender_email="sam@example.com")
    assert any("unsubscribe" in f.message.lower() for f in report.findings)


def test_attachment_mode_is_flagged():
    report = scorer.score(_content(attach_mode="attach", attachment_path=__file__),
                          sender_email="sam@example.com")
    assert any(f.category == "Attachment" for f in report.findings)


# --- DNS record generation and parsing --------------------------------------
def test_generate_spf_merges_providers_without_duplicates():
    record, warnings = dns_tools.generate_spf(
        ["Google Workspace", "Microsoft 365"], ipv4=["203.0.113.0/24"])
    assert record.startswith("v=spf1")
    assert record.endswith("~all")
    assert record.count("include:_spf.google.com") == 1
    assert "ip4:203.0.113.0/24" in record
    assert warnings == []


def test_generate_spf_rejects_bad_ip():
    _, warnings = dns_tools.generate_spf([], ipv4=["not-an-ip"])
    assert warnings and "not a valid" in warnings[0]


def test_generate_spf_strict():
    record, _ = dns_tools.generate_spf(["Google Workspace"], strict=True)
    assert record.endswith("-all")


def test_generate_dmarc():
    record, warnings = dns_tools.generate_dmarc("quarantine", rua="d@x.com")
    assert "v=DMARC1" in record and "p=quarantine" in record
    assert "rua=mailto:d@x.com" in record
    assert warnings == []

    _, warnings = dns_tools.generate_dmarc("none")
    assert warnings, "missing rua should warn"


def test_generate_dmarc_reject_warns():
    _, warnings = dns_tools.generate_dmarc("reject", rua="d@x.com")
    assert any("reject" in w for w in warnings)


def test_dkim_keypair_is_valid(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "KEYS_DIR", tmp_path)
    result = dns_tools.generate_dkim_keypair("mail", "example.com", bits=1024)
    assert result["host"] == "mail._domainkey.example.com"
    assert result["record"].startswith("v=DKIM1; k=rsa; p=")
    assert "BEGIN RSA PRIVATE KEY" in result["private_key"]

    import base64
    from cryptography.hazmat.primitives import serialization

    encoded = result["record"].split("p=")[1]
    key = serialization.load_der_public_key(base64.b64decode(encoded))
    assert key.key_size == 1024


def test_normalise_domain():
    assert dns_tools.normalise_domain("a@Example.com") == "example.com"
    assert dns_tools.normalise_domain("https://Example.com/path") == "example.com"
    assert dns_tools.normalise_domain(" example.com ") == "example.com"


def test_spf_lookup_counter():
    # 3 includes, counted without network access to the nested records
    record = "v=spf1 include:a.com include:b.com include:c.com ~all"
    assert dns_tools._count_spf_lookups(record, depth=5) == 3


# --- send window ------------------------------------------------------------
def test_send_window_respects_hours_and_weekend():
    from datetime import datetime

    from app.core import sender

    plan = sender.SendPlan(
        campaign_id=0,
        sender=composer.SenderIdentity("A", "a@b.com"),
        content=_content(),
        smtp=sender.SmtpSettings("h", 587, "u", "p"),
        window_start="09:00", window_end="18:00", weekdays_only=True, skip_holidays=False)

    assert sender.in_send_window(plan, datetime(2026, 9, 14, 10, 0))[0] is True    # Monday
    assert sender.in_send_window(plan, datetime(2026, 9, 14, 22, 0))[0] is False   # night
    assert sender.in_send_window(plan, datetime(2026, 9, 14, 8, 59))[0] is False   # too early
    assert sender.in_send_window(plan, datetime(2026, 9, 13, 10, 0))[0] is False   # Sunday


def test_next_window_open_skips_weekend():
    from datetime import datetime

    from app.core import sender

    plan = sender.SendPlan(
        campaign_id=0, sender=composer.SenderIdentity("A", "a@b.com"), content=_content(),
        smtp=sender.SmtpSettings("h", 587, "u", "p"),
        window_start="09:00", window_end="18:00", weekdays_only=True, skip_holidays=False)

    # Friday evening -> next opening is Monday morning
    resume = sender.next_window_open(plan, datetime(2026, 9, 11, 19, 0))
    assert resume.weekday() == 0
    assert resume.hour == 9


def test_smtp_security_inferred_from_port():
    from app.core import sender

    assert sender.SmtpSettings("h", 465, "u", "p").resolved_security() == "ssl"
    assert sender.SmtpSettings("h", 587, "u", "p").resolved_security() == "starttls"
    assert sender.SmtpSettings("h", 465, "u", "p", security="none").resolved_security() == "none"


# --- warm-up ----------------------------------------------------------------
def test_warmup_cap_respects_provider_limit():
    from app.core import warmup

    db.set_setting("warmup_enabled", True)
    db.set_setting("provider_limit", 10)
    assert warmup.status().cap <= 10
    db.set_setting("provider_limit", 500)


def test_warmup_records_sends():
    from app.core import warmup

    before = warmup.status().sent_today
    warmup.record_sent(3)
    assert warmup.status().sent_today == before + 3


# --- the stored inbox -------------------------------------------------------
def _sample_message(raw: str):
    import email

    return email.message_from_string(raw)


REPLY_MESSAGE = """From: "Lead Person" <lead@inboxtest.test>
To: me@mine.test
Subject: Re: Quick question
Date: Tue, 15 Sep 2026 14:32:11 +0100
Content-Type: text/plain; charset="utf-8"

Yes please send the brochure.
"""

HTML_MESSAGE = """From: Someone <html@inboxtest.test>
Subject: =?utf-8?q?A_caf=C3=A9_note?=
Date: Mon, 14 Sep 2026 09:00:00 +0000
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<html><body><style>p{color:red}</style><p>Hello&nbsp;&amp; welcome</p></body></html>
"""


def test_reply_is_classified_and_readable():
    from app.core import imap_sync

    db.execute("INSERT INTO contacts(email, company, person, valid) VALUES (?,?,?,1)",
               ("lead@inboxtest.test", "Acme", "Lead Person"))
    message = _sample_message(REPLY_MESSAGE)
    result = imap_sync.SyncResult()

    kind, known = imap_sync._classify(message, result)
    assert (kind, known) == ("reply", True)
    assert imap_sync.sender_name(message) == "Lead Person"
    assert imap_sync.readable_body(message) == "Yes please send the brochure."
    assert imap_sync.received_at(message).startswith("2026-09-15T")


def test_html_only_message_is_stored_as_text():
    from app.core import imap_sync

    message = _sample_message(HTML_MESSAGE)
    body = imap_sync.readable_body(message)
    assert "<p>" not in body and "color:red" not in body
    assert "Hello" in body and "welcome" in body
    # A header encoded per RFC 2047 has to come back as the characters it means
    assert "café" in imap_sync._decode_header(message.get("Subject"))


def test_mail_from_a_stranger_is_kept_but_not_counted_as_a_reply():
    from app.core import imap_sync

    result = imap_sync.SyncResult()
    kind, known = imap_sync._classify(_sample_message(HTML_MESSAGE), result)
    assert (kind, known) == ("other", False)
    assert result.replies == []


def test_saved_message_survives_a_second_fetch_of_the_same_uid():
    db.clear_inbox()
    db.save_message("INBOX", 42, from_name="A", from_email="a@x.test", subject="First",
                    body="one", received_at="2026-09-16T10:00:00", kind="reply", known=True)
    stored = db.inbox_messages()[0]
    assert db.inbox_unseen() == 1

    db.mark_message_seen(stored["id"])
    db.save_message("INBOX", 42, from_name="A", from_email="a@x.test", subject="Second",
                    body="two", received_at="2026-09-16T10:00:00", kind="reply", known=True)

    rows = db.inbox_messages()
    assert len(rows) == 1                 # the same UID is the same message
    assert rows[0]["subject"] == "Second"  # with its content brought up to date
    assert rows[0]["seen"] == 1            # and still marked as read
    assert db.inbox_unseen() == 0


def test_inbox_filters_and_trim():
    db.clear_inbox()
    for n, kind in enumerate(("reply", "bounce", "optout", "other", "reply")):
        db.save_message("INBOX", 200 + n, from_name=f"S{n}", from_email="s@x.test",
                        subject=f"M{n}", body="b", received_at=f"2026-09-{n + 1:02d}T10:00:00",
                        kind=kind, known=False)
    assert len(db.inbox_messages()) == 5
    assert len(db.inbox_messages("reply")) == 2
    assert len(db.inbox_messages("bounce")) == 1
    assert db.inbox_messages("no-such-kind") == []

    db.trim_inbox(2)
    kept = db.inbox_messages()
    assert len(kept) == 2
    assert [r["subject"] for r in kept] == ["M4", "M3"]  # the newest survive

    db.mark_all_messages_seen()
    assert db.inbox_unseen() == 0


def test_a_badly_labelled_message_does_not_abort_the_check():
    """Mail in the wild lies about charsets, and one bad message used to lose the lot.

    A made-up charset name makes bytes.decode raise LookupError rather than
    UnicodeDecodeError, which escaped the sync and abandoned the whole inbox
    check. A part labelled ASCII that is not ASCII is almost always UTF-8.
    """
    from app.core import imap_sync

    made_up = _sample_message(
        "From: Lead <lead@inboxtest.test>\n"
        "Subject: Re: charset\n"
        'Content-Type: text/plain; charset="totally-made-up"\n'
        "\n"
        "plain words\n")
    assert imap_sync.readable_body(made_up) == "plain words"
    assert imap_sync.is_unsubscribe(made_up) is False   # this reads the body too

    mislabelled = _sample_message(
        "From: Lead <lead@inboxtest.test>\n"
        "Subject: Re: accents\n"
        'Content-Type: text/plain; charset="us-ascii"\n'
        "\n"
        "Caf\u00e9 r\u00e9sum\u00e9\n")
    assert imap_sync.readable_body(mislabelled) == "Caf\u00e9 r\u00e9sum\u00e9"


def test_only_the_readable_parts_of_a_message_are_kept():
    """An attached file must not end up in the body text, and plain text wins."""
    from app.core import imap_sync

    message = _sample_message(
        "From: Lead <lead@inboxtest.test>\n"
        "Subject: Re: attached\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/mixed; boundary="A"\n'
        "\n"
        "--A\n"
        'Content-Type: multipart/alternative; boundary="B"\n'
        "\n"
        "--B\n"
        "Content-Type: text/plain\n"
        "\n"
        "The plain version.\n"
        "--B\n"
        "Content-Type: text/html\n"
        "\n"
        "<p>The HTML version.</p>\n"
        "--B--\n"
        "\n"
        "--A\n"
        'Content-Type: application/pdf; name="prices.pdf"\n'
        "Content-Transfer-Encoding: base64\n"
        "\n"
        "JVBERi0xLjQK\n"
        "\n"
        "--A--\n")
    body = imap_sync.readable_body(message)
    assert body == "The plain version."
    assert "JVBERi" not in body

# --- import: short write transactions ---------------------------------------
def test_import_commits_in_batches_rather_than_holding_one_transaction():
    """A long transaction on a worker thread freezes the window.

    SQLite allows one writer. The import used to open a transaction, do every
    DNS lookup inside it, and commit at the end, so the UI thread's own next
    write queued behind it until the connection timed out. That is thirty
    seconds of a window that does not repaint.
    """
    import pandas as pd

    from app.core import importer

    assert importer.COMMIT_EVERY <= 500, "a batch this big holds the lock too long"

    rows = importer.COMMIT_EVERY * 2 + 10
    frame = pd.DataFrame({
        "Email": [f"batch{n}@batchtest.test" for n in range(rows)],
        "Company": [f"Co {n}" for n in range(rows)],
    })
    commits = []
    real_connect = db.connect

    class Counting:
        """Wraps the connection so commits can be counted."""

        def __init__(self, inner):
            self._inner = inner

        def commit(self):
            commits.append(1)
            return self._inner.commit()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    db.connect = lambda: Counting(real_connect())
    try:
        result = importer.import_dataframe(
            frame, importer.ColumnMapping(email="Email", company="Company"),
            source_file="batch.xlsx", check_mx=False)
    finally:
        db.connect = real_connect

    assert result.imported == rows
    assert len(commits) >= 3, f"only committed {len(commits)} times for {rows} rows"
    db.execute("DELETE FROM contacts WHERE email LIKE '%@batchtest.test'")


def test_domains_are_resolved_once_each_and_before_any_writing():
    """One lookup per domain, not one per row, and none inside a transaction."""
    import pandas as pd

    from app.core import dns_tools, importer

    frame = pd.DataFrame({"Email": [f"p{n}@dom{n % 4}.test" for n in range(40)]})
    assert importer.domains_in(frame, "Email") == [f"dom{n}.test" for n in range(4)]

    asked = []
    real = dns_tools.has_mx
    dns_tools.has_mx = lambda domain: (asked.append(domain), True)[1]
    try:
        answers = importer.resolve_domains(importer.domains_in(frame, "Email"))
    finally:
        dns_tools.has_mx = real
    assert len(asked) == 4 == len(answers)
    assert all(answers.values())


def test_a_busy_write_is_skipped_rather_than_raised():
    """execute_soft is for writes nobody would miss. It must not raise."""
    assert db.set_setting_soft("test_soft_key", "value") is True
    assert db.get_setting("test_soft_key") == "value"
    # A statement that cannot work still must not raise out of execute_soft
    assert db.execute_soft("UPDATE no_such_table SET x = 1") is False


# --- contact list sorting ---------------------------------------------------
def test_every_sort_order_works_and_puts_blanks_last():
    from app.models.contacts_model import SORTS, ContactsModel

    db.execute("DELETE FROM contacts")
    people = [
        ("zara@z.test", "Zenith", "Zara", "2026-01-05"),
        ("adam@a.test", "apex", "adam", "2026-03-11"),
        ("mia@m.test", "", "Mia", "2026-02-02"),
        ("ben@b.test", None, None, "2026-04-14"),
    ]
    for email, company, person, when in people:
        db.execute("INSERT INTO contacts(email, company, person, valid, imported_at) "
                   "VALUES (?,?,?,1,?)", (email, company, person, f"{when}T09:00:00"))
    db.execute("UPDATE contacts SET bounced_at = ? WHERE email = ?",
               ("2026-05-01T09:00:00", "ben@b.test"))

    model = ContactsModel()
    for key, _label in SORTS:
        model.set_sort(key)
        model.reload()
        assert model.rowCount() == len(people), f"{key} lost rows"

    model.set_sort("email_az")
    model.reload()
    assert [r["email"] for r in model._rows] == [
        "adam@a.test", "ben@b.test", "mia@m.test", "zara@z.test"]

    model.set_sort("email_za")
    model.reload()
    assert [r["email"] for r in model._rows][0] == "zara@z.test"

    # Case-insensitive, and the rows with no company come last in both directions
    model.set_sort("company_az")
    model.reload()
    assert [r["company"] for r in model._rows] == ["apex", "Zenith", "", ""]
    model.set_sort("company_za")
    model.reload()
    assert [r["company"] for r in model._rows] == ["Zenith", "apex", "", ""]

    model.set_sort("status")
    model.reload()
    assert model._rows[0]["_status"] == "Bounced"

    model.set_sort("newest")
    model.reload()
    assert model._rows[0]["email"] == "ben@b.test"

    # An unknown key changes nothing rather than breaking the query
    model.set_sort("nonsense")
    model.reload()
    assert model.sort_key() == "newest" and model.rowCount() == len(people)


def test_paging_is_stable_when_the_sort_column_is_full_of_ties():
    """Without a tiebreak, LIMIT/OFFSET can repeat rows and skip others."""
    from app.models.contacts_model import PAGE_SIZE, ContactsModel

    db.execute("DELETE FROM contacts")
    total = PAGE_SIZE * 2 + 25
    db.execute_many(
        "INSERT INTO contacts(email, company, person, valid, imported_at) VALUES (?,?,?,1,?)",
        [(f"t{n:05d}@tie.test", "Same Company", "Same Person", "2026-01-01T09:00:00")
         for n in range(total)])

    model = ContactsModel()
    model.set_sort("company_az")
    model.reload()
    while model.canFetchMore():
        model.fetchMore()
    emails = [r["email"] for r in model._rows]
    assert len(emails) == total
    assert len(set(emails)) == total, "paging showed a row twice"
    db.execute("DELETE FROM contacts")


# --- the preview picks variants independently -------------------------------
def test_preview_can_pair_any_subject_with_any_body():
    """One shared index meant subject 2 could only ever appear with body 2."""
    from app.core import composer, merge
    from app.workers import jobs

    content = composer.Content(
        subject_variants=["First subject", "Second subject", "Third subject"],
        body_variants=["<p>Body one</p>", "<p>Body two</p>"],
    )
    context = merge.build_context({"email": "a@b.test", "company": "Acme", "person": "Ann"})
    identity = composer.SenderIdentity(name="Me", email="me@mine.test")

    seen = set()
    for subject_index in range(3):
        for body_index in range(2):
            subject, _html, text = jobs.build_preview(
                identity, context, content, subject_index, body_index, 1)
            seen.add((subject, "one" if "Body one" in text else "two"))
    assert len(seen) == 6, "not every combination is reachable"


def test_next_contact_never_shows_the_same_variant_twice_in_a_row():
    from app.ui.pages.templates import TemplatesPage

    for count in (2, 3, 4, 7):
        current = 0
        for _ in range(40):
            nxt = TemplatesPage._another(current, count)
            assert 0 <= nxt < count
            assert nxt != current, f"repeated {nxt} with {count} to choose from"
            current = nxt
    # A single variant has nowhere to go, and must not spin or raise
    assert TemplatesPage._another(0, 1) == 0
    assert TemplatesPage._another(0, 0) == 0


# --- the built-in examples --------------------------------------------------
@pytest.mark.parametrize("code", ["en", "ar", "de", "es", "fr"])
def test_the_built_in_examples_score_well_and_reach_the_main_inbox(code):
    """The examples are what a new user starts from, in their own language.

    Every subject paired with every message is scored as the finished email,
    for a real-looking contact, with the unsubscribe line off as the guide
    recommends for personal outreach. Read app/core/examples.py before editing.
    """
    from app import i18n
    from app.core import examples

    i18n.set_language(code)
    try:
        sample = examples.for_language(code)
        content = composer.Content(
            subject_variants=list(sample["subjects"]), body_variants=list(sample["bodies"]),
            signature_html=sample["signature"], attach_mode="none", unsubscribe_note=False)
        context = merge.build_context({"email": "sarah@acme.test", "person": "Sarah Jones",
                                       "company": "Acme Trading"})
        for subject_index in range(len(sample["subjects"])):
            for body_index in range(len(sample["bodies"])):
                report = scorer.score(content, sender_email="hello@mycompany.com",
                                      context=context, subject_index=subject_index,
                                      body_index=body_index)
                assert report.score >= 90 and report.landing == scorer.PRIMARY, (
                    f"{code} subject {subject_index + 1} message {body_index + 1}: "
                    f"{report.score} {report.landing}: "
                    + "; ".join(f.message for f in report.by_severity()))

        assert len(sample["subjects"]) >= 3 and len(sample["bodies"]) >= 2
        for subject in sample["subjects"]:
            assert 15 <= len(subject) <= 70, subject
            assert not merge.unresolved_tags(subject, merge.BUILTIN_TAGS), subject
        for body in sample["bodies"]:
            words = len(composer.html_to_text(body).split())
            assert 40 <= words <= 150, f"{words} words"
            assert not merge.unresolved_tags(body, merge.BUILTIN_TAGS)
            assert merge.validate_spintax(body) is None
    finally:
        i18n.set_language("en")


# --- v0.7.0: the score reads the finished email -----------------------------
def test_the_score_reads_the_finished_email_not_the_parts():
    """A link only in the signature, and a tag empty for this contact, only show up together."""
    content = _content(
        body_variants=["Hi {{FirstName}},\n\nWe make office furniture in {{City}} for teams like "
                       "yours and would like to hear how you furnish new offices. Would a "
                       "short call next week be useful?"],
        signature_html='Sam Taylor<br>+1 555 010 0000<br><a href="https://bit.ly/x">site</a>',
        attach_mode="none", unsubscribe_note=False)
    context = merge.build_context({"email": "a@b.test", "person": "Ann", "company": "Acme"},
                                  ["City"])
    report = scorer.score(content, sender_email="sam@example.com", context=context)
    messages = " ".join(f.message for f in report.findings)
    assert "bit.ly" in messages                      # the link is in the signature
    assert "{{City}}" in messages and "blank" in messages
    assert report.version == "Subject 1 and message 1"


def test_a_tag_left_in_the_finished_email_is_critical():
    content = _content(body_variants=["Hi {{FirstName}}, about {{Region}}. Would a call help?"])
    report = scorer.score(content, sender_email="sam@example.com",
                          known_tags=merge.BUILTIN_TAGS + ["Region"])
    assert any(f.severity == "critical" and "{{Region}}" in f.message for f in report.findings)
    assert report.landing == scorer.SPAM


def test_marketing_signals_point_to_the_promotions_tab():
    content = _content(
        subject_variants=["Our spring newsletter for {{Company}}"],
        body_variants=["Hi {{FirstName}},\n\n- New range\n- Special price on every order\n"
                       "- <strong>Exclusive</strong> deal this month\n\nSee "
                       '<a href="https://example.com/a">the range</a> and '
                       '<a href="https://example.com/b">prices</a>. Shop now?'],
        unsubscribe_note=True)
    report = scorer.score(content, sender_email="sam@example.com", reply_to="sam@example.com")
    assert report.landing == scorer.PROMOTIONS, [f.message for f in report.findings]
    assert any(f.category == "Promotions tab" for f in report.findings)


def test_the_unsubscribe_footer_follows_the_app_language():
    from app import i18n

    i18n.set_language("de")
    try:
        footer = composer.unsubscribe_footer(composer.SenderIdentity("A", "a@b.test"))
    finally:
        i18n.set_language("en")
    assert "Abmelden" in footer


def test_an_arabic_email_is_laid_out_right_to_left():
    html = composer.assemble_html("مرحبًا أحمد، كيف حالكم؟", _content(unsubscribe_note=False),
                                  composer.SenderIdentity("A", "a@b.test"))
    assert 'dir="rtl"' in html
    assert 'dir="rtl"' not in composer.assemble_html(
        "Hello Ahmed", _content(unsubscribe_note=False), composer.SenderIdentity("A", "a@b.test"))


def test_a_column_empty_for_one_contact_is_left_blank_not_sent_as_a_tag():
    context = merge.build_context({"email": "a@b.test", "person": "Ann"}, ["City"])
    assert merge.render("in {{City}}.", context) == "in ."


# --- typed messages -----------------------------------------------------------
def test_typed_text_keeps_its_lines_paragraphs_and_bullets():
    """Most users never write HTML, and in HTML a typed line break vanishes."""
    html = composer.text_to_html("Hi {{FirstName}},\n\nLine one\nline two\n\nWe offer:\n"
                                 "- Fast delivery\n- Fair prices\n\nThanks")
    assert html == ("<p>Hi {{FirstName}},</p>\n\n<p>Line one<br>\nline two</p>\n\n"
                    "<p>We offer:</p>\n\n<ul>\n  <li>Fast delivery</li>\n  <li>Fair prices</li>\n"
                    "</ul>\n\n<p>Thanks</p>")


def test_a_message_already_in_html_is_left_as_written():
    written = "<p>Hello</p>\nstill the same paragraph"
    assert composer.text_to_html(written) == written


def test_a_subject_typed_over_several_lines_is_sent_as_one():
    identity = composer.SenderIdentity(name="", email="me@example.com")
    content = composer.Content(subject_variants=["Hello\n{{Company}}  team"],
                               body_variants=["Line one\nLine two"])
    message, subject, _ = composer.build_message(identity, "x@y.com", {"Company": "Acme"}, content)
    assert subject == "Hello Acme team"
    assert "Line one<br>" in message.get_body(("html",)).get_content()


# --- v0.6.2: unsubscribe switch ---------------------------------------------
def test_switching_the_unsubscribe_line_off_drops_the_footer_and_the_header():
    identity = composer.SenderIdentity("Sam Taylor", "sam@example.com")
    context = merge.build_context({"email": "x@y.com", "person": "Ahmed", "company": "Acme"})
    message, _subject, _ = composer.build_message(
        identity, "x@y.com", context, _content(unsubscribe_note=False))
    body = message.get_body(preferencelist=("html",)).get_content()
    assert "Unsubscribe" not in body
    assert "List-Unsubscribe" not in message
    assert "List-Unsubscribe-Post" not in message


def test_a_missing_unsubscribe_line_is_only_a_small_deduction():
    report = scorer.score(_content(unsubscribe_note=False), sender_email="sam@example.com")
    found = [f for f in report.findings if "unsubscribe" in f.message.lower()]
    assert found and all(f.severity == "low" for f in found)


# --- v0.6.2: every spreadsheet column becomes a tag -------------------------
def test_every_column_is_a_tag_even_when_blank_in_the_first_rows():
    columns = {f"Column {n}": [""] * 30 + [f"value {n}"] for n in range(12)}
    df = pd.DataFrame({"EMAIL": [f"wide{n}@example.com" for n in range(31)], **columns,
                       "Phone No.": ["555"] * 31, "Website / URL": ["x.com"] * 31})
    importer.import_dataframe(df, importer.detect_columns(df), check_mx=False)
    names = importer.merge_tag_names()
    for n in range(12):
        assert f"Column {n}" in names
    assert "Phone No." in names and "Website / URL" in names


def test_headings_with_punctuation_work_as_tags():
    context = {"Phone No.": "555", "Website / URL": "x.com", "FirstName": "Sam"}
    assert merge.render("{{Phone No.}} {{ Website / URL }} {{FirstName}}", context) == \
        "555 x.com Sam"
    assert merge.unresolved_tags("{{Phone No.}}", list(context)) == []


# --- v0.6.2: subjects and messages from a spreadsheet -----------------------
def test_subjects_and_messages_are_read_by_heading(tmp_path):
    path = tmp_path / "message.xlsx"
    pd.DataFrame({
        "Subject line": ["Hello {{Company}}", "A question", "Hello {{Company}}"],
        # A plain line break, as Excel's Alt+Enter makes. Carriage returns are
        # tested on their own below: pandas 3 writes "\r\n" into a file as two
        # line breaks, so it cannot be round-tripped through to_excel here.
        "Email body": ["Hi {{FirstName}},\nLine two", "", "Second message"],
        "Signature": ["Sam\nAcme", "", ""],
        "Notes": ["ignored", "", ""],
    }).to_excel(path, index=False)
    sheet = importer.read_templates(path)
    assert sheet.subjects == ["Hello {{Company}}", "A question"]
    assert sheet.bodies == ["Hi {{FirstName}},\nLine two", "Second message"]
    assert sheet.signature == "Sam\nAcme"


@pytest.mark.parametrize("raw", ["a_x000D_\nb", "a\r\r\nb", "a_x000D_\r\nb", "a\r\nb", "a\rb"])
def test_every_form_of_an_excel_line_break_becomes_one_new_line(raw):
    """Library versions unpack Excel's escaped carriage return differently."""
    assert importer._cell_text(raw) == "a\nb"


def test_a_sheet_without_headings_is_subjects_then_messages(tmp_path):
    path = tmp_path / "plain.csv"
    pd.DataFrame({"A": ["Subject one"], "B": ["Message one"]}).to_csv(path, index=False)
    sheet = importer.read_templates(path)
    assert sheet.subjects == ["Subject one"] and sheet.bodies == ["Message one"]


def test_the_blank_sheet_reads_back_in(tmp_path):
    path = importer.write_template_sample(tmp_path / "blank.xlsx", ["S1", "S2"], ["B1"], "Sig")
    sheet = importer.read_templates(path)
    assert sheet.subjects == ["S1", "S2"] and sheet.bodies == ["B1"] and sheet.signature == "Sig"


# --- v0.6.2: the permanent sent history -------------------------------------
def _sent_contact(email: str) -> int:
    return db.execute("INSERT INTO contacts(email, company, person, valid, imported_at) "
                      "VALUES (?, 'Co', 'Someone', 1, ?)", (email, db.now()))


def _campaign() -> int:
    return db.execute("INSERT INTO campaigns(name, created_at) VALUES ('t', ?)", (db.now(),))


def test_sent_history_keeps_the_message_and_survives_the_contact_being_deleted():
    contact_id = _sent_contact("kept@example.com")
    contact = db.query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    db.log_sent(campaign_id=_campaign(), contact=contact, status="sent", subject="Hello",
                body_html="<p>The whole message</p>", sent_at=db.now())
    db.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))

    row = db.query_one("SELECT id FROM sent_log WHERE email = 'kept@example.com'")
    message = db.sent_message(row["id"])
    assert message["body_html"] == "<p>The whole message</p>"
    assert message["subject"] == "Hello" and message["company"] == "Co"


def test_a_retry_updates_the_one_history_row():
    contact_id = _sent_contact("retry@example.com")
    campaign_id = _campaign()
    contact = db.query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    db.log_sent(campaign_id=campaign_id, contact=contact, status="failed", last_error="x")
    db.log_sent(campaign_id=campaign_id, contact=contact, status="sent", subject="S",
                body_html="<p>b</p>", sent_at=db.now())
    rows = db.query("SELECT * FROM sent_log WHERE email = 'retry@example.com'")
    assert len(rows) == 1
    assert rows[0]["status"] == "sent" and rows[0]["attempts"] == 2
    assert rows[0]["last_error"] is None


def test_deleting_history_never_lets_the_same_person_be_emailed_again():
    contact_id = _sent_contact("once@example.com")
    campaign_id = _campaign()
    db.execute("INSERT INTO campaign_recipients(campaign_id, contact_id, status, sent_at) "
               "VALUES (?, ?, 'sent', ?)", (campaign_id, contact_id, db.now()))
    contact = db.query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    db.log_sent(campaign_id=campaign_id, contact=contact, status="sent", sent_at=db.now())

    db.clear_sent()
    assert db.query_one("SELECT COUNT(*) AS n FROM sent_log")["n"] == 0
    still = db.query_one("SELECT status FROM campaign_recipients WHERE contact_id = ?",
                         (contact_id,))
    assert still["status"] == "sent"


def test_upgrading_copies_the_old_history_across(tmp_path):
    """A v0.6.1 database has its sends in campaign_recipients only."""
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(db._SCHEMA.split("-- The permanent record")[0])
    old.execute("INSERT INTO schema_info(version) VALUES (1)")
    old.execute("INSERT INTO contacts(id, email, company) VALUES (1, 'old@example.com', 'Old')")
    old.execute("INSERT INTO campaigns(id, name) VALUES (1, 'c')")
    old.execute("INSERT INTO campaign_recipients(campaign_id, contact_id, status, subject_used, "
                "sent_at) VALUES (1, 1, 'sent', 'Before', '2026-09-01T10:00:00')")
    old.commit()
    old.close()

    db.close()
    try:
        db.init(path)
        row = db.query_one("SELECT * FROM sent_log")
        assert row["email"] == "old@example.com" and row["subject"] == "Before"
        assert db.query_one("SELECT version FROM schema_info")["version"] == db.SCHEMA_VERSION
    finally:
        db.close()
        db.init(os.path.join(tempfile.mkdtemp(), "test.db"))


def test_the_send_worker_saves_a_copy_of_every_email_it_sends(monkeypatch):
    """End to end through the real worker, with the mail server faked."""
    import queue

    from app.core import sender, warmup

    class FakeServer:
        def send_message(self, message):
            self.last = message

        def quit(self):
            pass

    monkeypatch.setattr(sender, "open_smtp", lambda _settings: FakeServer())
    monkeypatch.setattr(sender, "in_send_window", lambda *_a, **_k: (True, ""))
    monkeypatch.setattr(warmup, "remaining_today", lambda *_a: 100)
    monkeypatch.setattr(warmup, "record_sent", lambda *_a: None)

    contact_id = _sent_contact("worker@example.com")
    campaign_id = _campaign()
    db.execute("INSERT INTO campaign_recipients(campaign_id, contact_id, status) "
               "VALUES (?, ?, 'pending')", (campaign_id, contact_id))
    plan = sender.SendPlan(
        campaign_id=campaign_id,
        sender=composer.SenderIdentity("Sam", "sam@example.com"),
        content=_content(unsubscribe_note=False),
        smtp=sender.SmtpSettings("smtp.example.com", 587, "u", "p"),
        delay_min_s=0, delay_max_s=0)
    worker = sender.SendWorker(plan, queue.Queue())
    worker.run()

    row = db.query_one("SELECT id, status, subject, from_addr FROM sent_log "
                       "WHERE email = 'worker@example.com'")
    assert row["status"] == "sent" and row["subject"] == "Office furniture for Co"
    assert row["from_addr"] == "Sam <sam@example.com>"
    body = db.sent_message(row["id"])["body_html"]
    assert "We make office furniture" in body and "Unsubscribe" not in body
