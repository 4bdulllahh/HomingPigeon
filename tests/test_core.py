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
    assert not any("unsubscribe" in f.message.lower() for f in report.findings)


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
