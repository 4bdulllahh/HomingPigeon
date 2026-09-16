"""SPF / DKIM / DMARC / MX / DNSBL checks and record generators.

All lookups go straight to DNS through dnspython. No third-party API, nothing
leaves the machine except the DNS queries themselves.
"""
from __future__ import annotations

import base64
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import dns.exception
import dns.rdatatype
import dns.resolver
import dns.reversename

from app import config

Status = Literal["pass", "warn", "fail", "info"]

_resolver = dns.resolver.Resolver()
_resolver.timeout = 5
_resolver.lifetime = 8

_mx_cache: dict[str, bool] = {}


@dataclass
class CheckResult:
    """One row in the deliverability report."""
    name: str
    status: Status
    summary: str
    detail: str = ""
    record: str = ""
    fix: str = ""
    extras: list[str] = field(default_factory=list)


# --- Low-level lookups ------------------------------------------------------
def _txt_records(name: str) -> list[str]:
    try:
        answers = _resolver.resolve(name, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers,
            dns.exception.Timeout, dns.name.LabelTooLong, ValueError):
        return []
    records = []
    for rdata in answers:
        # Long TXT values arrive as multiple strings and must be concatenated
        joined = "".join(part.decode("utf-8", "replace") for part in rdata.strings)
        records.append(joined)
    return records


def _mx_records(domain: str) -> list[tuple[int, str]]:
    try:
        answers = _resolver.resolve(domain, "MX")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers,
            dns.exception.Timeout, ValueError):
        return []
    return sorted((r.preference, str(r.exchange).rstrip(".")) for r in answers)


def has_mx(domain: str) -> bool:
    """Does this domain accept mail at all? Cached; falls back to an A record."""
    domain = domain.lower().strip()
    if domain in _mx_cache:
        return _mx_cache[domain]
    result = bool(_mx_records(domain))
    if not result:
        try:
            _resolver.resolve(domain, "A")
            result = True  # no MX but an A record: RFC 5321 implicit MX
        except Exception:
            result = False
    _mx_cache[domain] = result
    return result


def normalise_domain(value: str) -> str:
    """Accept an email address, a URL or a bare domain."""
    text = (value or "").strip().lower()
    if "@" in text:
        text = text.split("@", 1)[1]
    text = re.sub(r"^https?://", "", text)
    return text.strip("/ ").split("/")[0]


# --- MX ---------------------------------------------------------------------
def check_mx(domain: str) -> CheckResult:
    records = _mx_records(domain)
    if not records:
        return CheckResult(
            "MX (mail routing)", "fail",
            "No MX records found",
            f"{domain} has no mail servers listed, so mail sent to this domain cannot be delivered.",
            fix="Add MX records at your DNS host, pointing at your email provider.",
        )
    lines = [f"{pref}  {host}" for pref, host in records]
    provider = identify_provider(records)
    return CheckResult(
        "MX (mail routing)", "pass",
        f"{len(records)} mail server(s) found" + (f" ({provider})" if provider else ""),
        "Mail for this domain is routed correctly.",
        record="\n".join(lines),
    )


PROVIDER_SIGNATURES = [
    ("google.com", "Google Workspace"),
    ("googlemail.com", "Google Workspace"),
    ("outlook.com", "Microsoft 365"),
    ("protection.outlook.com", "Microsoft 365"),
    ("zoho.com", "Zoho Mail"),
    ("zoho.eu", "Zoho Mail"),
    ("titan.email", "Titan"),
    ("secureserver.net", "GoDaddy"),
    ("mail.protonmail.ch", "Proton Mail"),
    ("messagingengine.com", "Fastmail"),
    ("emailsrvr.com", "Rackspace"),
    ("hostinger", "Hostinger"),
    ("cpanel", "cPanel / shared hosting"),
]


def identify_provider(mx_records: list[tuple[int, str]]) -> str:
    hosts = " ".join(h.lower() for _, h in mx_records)
    for needle, label in PROVIDER_SIGNATURES:
        if needle in hosts:
            return label
    return ""


# --- SPF --------------------------------------------------------------------
SPF_LOOKUP_MECHANISMS = ("include:", "a:", "mx:", "ptr", "exists:", "redirect=")


def _count_spf_lookups(record: str, depth: int = 0, seen: set[str] | None = None) -> int:
    """Count DNS-querying mechanisms, recursing into includes (the 10 limit is total)."""
    if depth > 5:
        return 0
    seen = seen if seen is not None else set()
    count = 0
    for term in record.split():
        lowered = term.lower()
        if lowered.startswith("include:") or lowered.startswith("redirect="):
            count += 1
            target = term.split(":", 1)[-1] if ":" in term else term.split("=", 1)[-1]
            target = target.strip().lower()
            if target and target not in seen:
                seen.add(target)
                for nested in _txt_records(target):
                    if nested.lower().startswith("v=spf1"):
                        count += _count_spf_lookups(nested, depth + 1, seen)
                        break
        elif lowered.startswith(("a:", "mx:", "exists:")) or lowered in ("a", "mx", "ptr"):
            count += 1
    return count


def check_spf(domain: str) -> CheckResult:
    records = [r for r in _txt_records(domain) if r.lower().startswith("v=spf1")]

    if not records:
        return CheckResult(
            "SPF", "fail",
            "No SPF record",
            "Without SPF, receiving servers cannot confirm your server is allowed to send "
            "for this domain. Cold email from an unauthenticated domain is very likely to be "
            "filtered as spam.",
            fix="Use the SPF generator below and add the result as a TXT record on your root domain.",
        )

    if len(records) > 1:
        return CheckResult(
            "SPF", "fail",
            f"{len(records)} SPF records, but there must be exactly one",
            "Publishing more than one SPF record is a permanent error (permerror): receivers "
            "treat SPF as broken and ignore it entirely. This is a common and silent mistake.",
            record="\n\n".join(records),
            fix="Merge all sending sources into a single TXT record and delete the others.",
        )

    record = records[0]
    lookups = _count_spf_lookups(record)
    extras = [f"DNS lookups used: {lookups} of 10 allowed"]

    all_match = re.search(r"([-~?+])all\b", record.lower())
    qualifier = all_match.group(1) if all_match else None

    if lookups > 10:
        return CheckResult(
            "SPF", "fail",
            f"Too many DNS lookups ({lookups} of 10)",
            "SPF allows a maximum of 10 DNS lookups. Over the limit, SPF returns permerror and "
            "receivers treat the message as unauthenticated.",
            record=record, extras=extras,
            fix="Remove unused include: entries, or replace them with the ip4:/ip6: addresses they resolve to.",
        )

    if qualifier is None:
        return CheckResult(
            "SPF", "warn",
            "SPF record has no 'all' mechanism",
            "Without a trailing ~all or -all, the record does not say what to do with servers "
            "that are not listed, so it gives receivers almost nothing to act on.",
            record=record, extras=extras,
            fix="Add ~all to the end of the record (or -all once you are confident it is complete).",
        )

    if qualifier == "+":
        return CheckResult(
            "SPF", "fail",
            "SPF ends with +all, which authorises the entire internet",
            "+all tells receivers that any server may send as your domain. It is worse than "
            "having no SPF at all and is often treated as a spam signal on its own.",
            record=record, extras=extras,
            fix="Replace +all with ~all (softfail) or -all (hardfail).",
        )

    if qualifier == "?":
        return CheckResult(
            "SPF", "warn",
            "SPF ends with ?all (neutral)",
            "A neutral result is treated almost the same as having no policy.",
            record=record, extras=extras,
            fix="Change ?all to ~all or -all.",
        )

    strength = "strict (-all)" if qualifier == "-" else "soft fail (~all)"
    status: Status = "pass"
    detail = f"SPF is published and valid, using {strength}."
    fix = ""
    if qualifier == "~" and lookups <= 8:
        detail += " Once you are sure every sending service is listed, tightening this to -all is stronger."
        fix = "Optional: change ~all to -all after confirming all senders are included."
    if lookups >= 9:
        status = "warn"
        detail += f" You are close to the 10-lookup limit ({lookups} used)."

    return CheckResult("SPF", status, f"Valid SPF record, {strength}", detail,
                       record=record, extras=extras, fix=fix)


SPF_PRESETS: dict[str, str] = {
    "Google Workspace": "include:_spf.google.com",
    "Microsoft 365": "include:spf.protection.outlook.com",
    "Zoho Mail": "include:zoho.com",
    "Zoho Mail (EU)": "include:zoho.eu",
    "Titan Email": "include:spf.titan.email",
    "GoDaddy (Workspace)": "include:secureserver.net",
    "Hostinger": "include:_spf.mail.hostinger.com",
    "cPanel / shared hosting": "a mx",
    "Mailchimp": "include:servers.mcsv.net",
    "SendGrid": "include:sendgrid.net",
    "Mailgun": "include:mailgun.org",
    "Amazon SES": "include:amazonses.com",
    "Brevo (Sendinblue)": "include:spf.brevo.com",
    "Zendesk": "include:mail.zendesk.com",
}


def generate_spf(providers: list[str], ipv4: list[str] | None = None,
                 ipv6: list[str] | None = None, strict: bool = False,
                 include_mx: bool = False) -> tuple[str, list[str]]:
    """Build a single SPF record. Returns (record, warnings)."""
    terms: list[str] = ["v=spf1"]
    warnings: list[str] = []
    seen: set[str] = set()

    if include_mx:
        terms.append("mx")

    for provider in providers:
        value = SPF_PRESETS.get(provider)
        if not value:
            continue
        for token in value.split():
            if token not in seen:
                seen.add(token)
                terms.append(token)

    for address in ipv4 or []:
        address = address.strip()
        if not address:
            continue
        try:
            ipaddress.ip_network(address, strict=False)
        except ValueError:
            warnings.append(f"'{address}' is not a valid IPv4 address or range, so it was skipped")
            continue
        terms.append(f"ip4:{address}")

    for address in ipv6 or []:
        address = address.strip()
        if not address:
            continue
        try:
            ipaddress.ip_network(address, strict=False)
        except ValueError:
            warnings.append(f"'{address}' is not a valid IPv6 address or range, so it was skipped")
            continue
        terms.append(f"ip6:{address}")

    terms.append("-all" if strict else "~all")
    record = " ".join(terms)

    lookups = sum(1 for t in terms if t.lower().startswith(("include:", "a:", "mx:", "exists:"))
                  or t.lower() in ("a", "mx"))
    if lookups > 10:
        warnings.append(f"This record uses about {lookups} DNS lookups; the limit is 10.")
    if len(record) > 255:
        warnings.append("Record is longer than 255 characters, so your DNS host must split it into "
                        "multiple strings within the same TXT record.")
    return record, warnings


# --- DKIM -------------------------------------------------------------------
COMMON_SELECTORS = [
    "google", "selector1", "selector2", "s1", "s2", "k1", "k2", "default",
    "dkim", "mail", "email", "smtp", "zoho", "zohomail", "titan1", "mandrill",
    "everlytickey1", "mxvault", "protonmail", "fm1", "sig1", "key1", "pic",
    "cm", "dk", "20230601", "20221208",
]


def find_dkim(domain: str, selectors: list[str] | None = None) -> list[tuple[str, str]]:
    """Probe selectors and return the ones that resolve, as (selector, record)."""
    found = []
    for selector in (selectors or COMMON_SELECTORS):
        selector = selector.strip()
        if not selector:
            continue
        for record in _txt_records(f"{selector}._domainkey.{domain}"):
            if "p=" in record.lower() or record.lower().startswith("v=dkim1"):
                found.append((selector, record))
                break
    return found


def _dkim_key_bits(record: str) -> int | None:
    match = re.search(r"p=([A-Za-z0-9+/=]+)", record)
    if not match:
        return None
    try:
        der = base64.b64decode(match.group(1) + "==")
    except Exception:
        return None
    # Rough size classes from the DER-encoded SubjectPublicKeyInfo length
    if len(der) < 150:
        return 512
    if len(der) < 200:
        return 1024
    if len(der) < 350:
        return 2048
    return 4096


def check_dkim(domain: str, selectors: list[str] | None = None) -> CheckResult:
    found = find_dkim(domain, selectors)

    if not found:
        return CheckResult(
            "DKIM", "warn",
            "No DKIM record found on the selectors tested",
            "DKIM signs each message so receivers can prove it was not altered and really came "
            "from your domain. It is also required for DMARC to pass in most setups.\n\n"
            "This check probes common selector names. If your provider uses an unusual one, "
            "enter it manually before concluding DKIM is missing.",
            fix="Enable DKIM in your email provider's admin console, then publish the TXT record "
                "they give you. See the DKIM section below for the exact steps per provider.",
        )

    lines = []
    problems = []
    for selector, record in found:
        bits = _dkim_key_bits(record)
        label = f"{selector}._domainkey.{domain}"
        lines.append(f"{label}\n{record}")
        if re.search(r"\bp=\s*(;|$)", record):
            problems.append(f"Selector '{selector}' has an empty public key (p=), which means the "
                            f"key has been revoked.")
        elif bits and bits < 1024:
            problems.append(f"Selector '{selector}' uses a {bits}-bit key; 1024 is the minimum and "
                            f"2048 is recommended.")

    if problems:
        return CheckResult(
            "DKIM", "warn",
            f"DKIM found on {len(found)} selector(s), with issues",
            "\n".join(problems), record="\n\n".join(lines),
            fix="Regenerate the key at 2048 bits in your provider's console and republish it.",
        )

    selectors_found = ", ".join(s for s, _ in found)
    return CheckResult(
        "DKIM", "pass",
        f"DKIM published on selector(s): {selectors_found}",
        "Your outgoing mail can be cryptographically signed, which receivers check on arrival.",
        record="\n\n".join(lines),
    )


DKIM_PROVIDER_STEPS: dict[str, str] = {
    "Google Workspace":
        "Admin console → Apps → Google Workspace → Gmail → Authenticate email → select your domain "
        "→ Generate new record (choose 2048-bit) → publish the TXT record shown at your DNS host → "
        "return and click Start authentication.",
    "Microsoft 365":
        "Microsoft 365 Defender portal → Email & collaboration → Policies & rules → Threat policies → "
        "Email authentication settings → DKIM → select your domain → publish the two CNAME records "
        "(selector1 and selector2) at your DNS host → set 'Sign messages' to Enabled.",
    "Zoho Mail":
        "Zoho Mail Admin Console → Domains → your domain → Email Configuration → DKIM → Add → "
        "enter a selector (e.g. 'zoho') → copy the generated TXT record to your DNS host → Verify.",
    "Titan Email":
        "Titan control panel → Settings → DNS records → enable DKIM → add the TXT record shown to "
        "your DNS host.",
    "cPanel / shared hosting":
        "cPanel → Email Deliverability → select your domain → Manage → cPanel shows the DKIM record "
        "it expects; use 'Install the suggested record' if your DNS is managed there, otherwise copy "
        "the TXT record to your DNS host.",
    "Own mail server (Postfix / Exim)":
        "Generate a key pair with the generator below, publish the public key as a TXT record at "
        "<selector>._domainkey.yourdomain, then configure OpenDKIM (or your MTA's signing module) "
        "with the private key file.",
}


def generate_dkim_keypair(selector: str, domain: str, bits: int = 2048) -> dict[str, str]:
    """Generate an RSA keypair and the TXT record for the public half.

    Only useful when you run your own mail server. Hosted providers (Google,
    Microsoft, Zoho) hold the signing key themselves and generate it for you.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")

    public_der = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_b64 = base64.b64encode(public_der).decode("ascii")

    config.ensure_dirs()
    safe_domain = re.sub(r"[^a-z0-9.\-]", "_", domain.lower())
    key_path = Path(config.KEYS_DIR) / f"{selector}.{safe_domain}.private.pem"
    key_path.write_text(private_pem, encoding="ascii")
    try:
        key_path.chmod(0o600)
    except OSError:
        pass

    return {
        "host": f"{selector}._domainkey.{domain}",
        "record": f"v=DKIM1; k=rsa; p={public_b64}",
        "private_key": private_pem,
        "private_key_path": str(key_path),
        "bits": str(bits),
    }


# --- DMARC ------------------------------------------------------------------
def check_dmarc(domain: str) -> CheckResult:
    records = [r for r in _txt_records(f"_dmarc.{domain}") if r.lower().startswith("v=dmarc1")]

    if not records:
        return CheckResult(
            "DMARC", "fail",
            "No DMARC record",
            "DMARC ties SPF and DKIM together and tells receivers what to do when a message fails "
            "authentication. Gmail and Yahoo now require a DMARC record from anyone sending in "
            "volume; without it, bulk mail is routinely rejected or spam-foldered.",
            fix="Start with a monitoring-only policy (p=none) using the generator below, then "
                "tighten it to quarantine and finally reject.",
        )

    if len(records) > 1:
        return CheckResult(
            "DMARC", "fail", f"{len(records)} DMARC records, but there must be exactly one",
            "Multiple DMARC records make the policy invalid and it is ignored.",
            record="\n\n".join(records), fix="Delete all but one record.",
        )

    record = records[0]
    tags = {}
    for part in record.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            tags[key.strip().lower()] = value.strip()

    policy = tags.get("p", "").lower()
    pct = tags.get("pct", "100")
    rua = tags.get("rua", "")
    extras = [f"Policy (p): {policy or 'missing'}"]
    if tags.get("sp"):
        extras.append(f"Subdomain policy (sp): {tags['sp']}")
    extras.append(f"Applied to: {pct}% of mail")
    extras.append(f"Aggregate reports (rua): {rua or 'not configured'}")
    if tags.get("adkim"):
        extras.append(f"DKIM alignment: {'strict' if tags['adkim'] == 's' else 'relaxed'}")
    if tags.get("aspf"):
        extras.append(f"SPF alignment: {'strict' if tags['aspf'] == 's' else 'relaxed'}")

    if not policy:
        return CheckResult(
            "DMARC", "fail", "DMARC record is missing the required p= tag",
            "Without a policy tag the record is invalid and receivers ignore it.",
            record=record, extras=extras, fix="Add p=none (then tighten later).",
        )

    if policy == "none":
        return CheckResult(
            "DMARC", "warn", "DMARC is monitoring only (p=none)",
            "A p=none policy publishes a record and collects reports, but instructs receivers to "
            "take no action on failures. It satisfies the basic requirement and is the correct "
            "place to start. It just does not protect your domain from being spoofed yet.",
            record=record, extras=extras,
            fix="After a few weeks of clean reports, move to p=quarantine, then p=reject."
                + ("" if rua else " Add a rua= address so you actually receive those reports."),
        )

    if pct and pct.isdigit() and int(pct) < 100:
        return CheckResult(
            "DMARC", "warn", f"DMARC p={policy} but only applied to {pct}% of mail",
            "The policy is only enforced on a sample of your mail.",
            record=record, extras=extras, fix="Raise pct to 100 once you are confident.",
        )

    return CheckResult(
        "DMARC", "pass", f"DMARC is enforcing (p={policy})",
        "Your domain tells receivers what to do with mail that fails authentication.",
        record=record, extras=extras,
        fix="" if rua else "Consider adding rua= to receive aggregate reports.",
    )


def generate_dmarc(policy: str = "none", rua: str = "", ruf: str = "", pct: int = 100,
                   subdomain_policy: str = "", strict_alignment: bool = False) -> tuple[str, list[str]]:
    terms = ["v=DMARC1", f"p={policy}"]
    warnings: list[str] = []

    if subdomain_policy:
        terms.append(f"sp={subdomain_policy}")
    if rua.strip():
        address = rua.strip()
        terms.append(f"rua=mailto:{address}" if not address.startswith("mailto:") else f"rua={address}")
    else:
        warnings.append("Without a rua= address you will not receive the reports that tell you "
                        "whether your authentication is actually working.")
    if ruf.strip():
        address = ruf.strip()
        terms.append(f"ruf=mailto:{address}" if not address.startswith("mailto:") else f"ruf={address}")
    if pct != 100:
        terms.append(f"pct={pct}")
    if strict_alignment:
        terms.extend(["adkim=s", "aspf=s"])

    if policy == "reject":
        warnings.append("p=reject is the strongest policy. Only move to it after your DMARC reports "
                        "show every legitimate sending source passing, or valid mail will be rejected.")
    return "; ".join(terms), warnings


# --- Blacklists -------------------------------------------------------------
DNSBL_ZONES = [
    ("Spamhaus ZEN", "zen.spamhaus.org"),
    ("SpamCop", "bl.spamcop.net"),
    ("Barracuda", "b.barracudacentral.org"),
    ("SORBS", "dnsbl.sorbs.net"),
    ("UCEPROTECT L1", "dnsbl-1.uceprotect.net"),
]


def resolve_host_ip(host: str) -> str | None:
    try:
        return socket.gethostbyname(host)
    except (socket.gaierror, OSError):
        return None


def check_blacklists(ip: str) -> CheckResult:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return CheckResult("Blacklists", "info", "No IP address to check",
                           "Enter or detect your sending server's IP address first.")
    if address.version != 4:
        return CheckResult("Blacklists", "info", "IPv6 blacklist checks are not supported",
                           "Most DNSBLs only publish IPv4 data.")

    reversed_ip = ".".join(reversed(str(address).split(".")))
    listed: list[str] = []
    errors = 0
    for label, zone in DNSBL_ZONES:
        try:
            _resolver.resolve(f"{reversed_ip}.{zone}", "A")
            listed.append(label)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            continue  # not listed: the expected result
        except Exception:
            errors += 1

    if listed:
        return CheckResult(
            "Blacklists", "fail", f"{ip} is listed on {len(listed)} blacklist(s)",
            "Listed on: " + ", ".join(listed) + ".\n\nWhile your sending IP is blacklisted, a large "
            "share of your mail will be rejected outright. If this is a shared hosting IP, the "
            "listing may be caused by another customer.",
            fix="Visit each blacklist's site to request delisting, and fix the cause first "
                "(compromised account, open relay, or a bad list). On shared hosting, contact your host.",
        )

    checked = len(DNSBL_ZONES) - errors
    return CheckResult(
        "Blacklists", "pass", f"{ip} is not listed on {checked} major blacklist(s)",
        "Checked: " + ", ".join(label for label, _ in DNSBL_ZONES) + ".",
    )


# --- Full report ------------------------------------------------------------
def full_report(domain: str, smtp_host: str = "", dkim_selectors: list[str] | None = None) -> list[CheckResult]:
    domain = normalise_domain(domain)
    if not domain:
        return [CheckResult("Domain", "fail", "No domain given", "Enter your sending domain first.")]

    results = [
        check_mx(domain),
        check_spf(domain),
        check_dkim(domain, dkim_selectors),
        check_dmarc(domain),
    ]
    if smtp_host:
        ip = resolve_host_ip(smtp_host)
        if ip:
            results.append(check_blacklists(ip))
        else:
            results.append(CheckResult("Blacklists", "warn", f"Could not resolve {smtp_host}",
                                       "The SMTP host name did not resolve to an IP address."))
    return results


def overall_grade(results: list[CheckResult]) -> tuple[Status, str]:
    if any(r.status == "fail" for r in results):
        return "fail", "Not ready to send. Fix the failures below first."
    if any(r.status == "warn" for r in results):
        return "warn", "Usable, but there are improvements worth making."
    return "pass", "Your domain is properly authenticated."
