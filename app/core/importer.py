"""Spreadsheet import: column auto-detection, validation, dedupe.

The source file is only ever read. Everything lands in the contacts table.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.core import db

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-']+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Header synonyms, scored against the sheet's real headers
EMAIL_HINTS = ["email", "e-mail", "mail", "email address", "e mail", "emailid", "email id", "mail id"]
COMPANY_HINTS = [
    "name of the company", "company", "company name", "organisation", "organization",
    "org", "business", "firm", "account", "client", "customer", "establishment",
]
PERSON_HINTS = [
    "contact person", "person", "contact", "name", "full name", "contact name",
    "attn", "attention", "recipient", "manager", "owner",
]

# Mailbox names that bounce and complain more than personal addresses
ROLE_PREFIXES = {
    "info", "sales", "admin", "support", "contact", "office", "hello", "enquiry",
    "enquiries", "inquiry", "careers", "hr", "jobs", "marketing", "help", "service",
    "noreply", "no-reply", "donotreply", "webmaster", "postmaster", "abuse", "billing",
}

# Common typos worth catching before they bounce
TYPO_DOMAINS = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gmail.co": "gmail.com",
    "gnail.com": "gmail.com", "gmail.con": "gmail.com", "hotmial.com": "hotmail.com",
    "hotmail.co": "hotmail.com", "yahho.com": "yahoo.com", "yahoo.co": "yahoo.com",
    "outlok.com": "outlook.com", "outloo.com": "outlook.com",
}


@dataclass
class ColumnMapping:
    email: str | None = None
    company: str | None = None
    person: str | None = None
    extras: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    total_rows: int = 0
    imported: int = 0
    updated: int = 0
    duplicates: int = 0
    invalid: int = 0
    suppressed: int = 0
    no_mx: int = 0
    risky: int = 0
    problems: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        bits = [f"{self.total_rows:,} rows read", f"{self.imported:,} imported"]
        if self.updated:
            bits.append(f"{self.updated:,} updated")
        if self.duplicates:
            bits.append(f"{self.duplicates:,} duplicates")
        if self.invalid:
            bits.append(f"{self.invalid:,} invalid")
        if self.no_mx:
            bits.append(f"{self.no_mx:,} dead domains")
        if self.suppressed:
            bits.append(f"{self.suppressed:,} suppressed")
        if self.risky:
            bits.append(f"{self.risky:,} flagged risky")
        return " · ".join(bits)


# --- Reading ----------------------------------------------------------------
def list_sheets(path: str | Path) -> list[str]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return ["CSV"]
    with pd.ExcelFile(path) as xl:
        return list(xl.sheet_names)


def read_sheet(path: str | Path, sheet: str | None = None, nrows: int | None = None) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        try:
            df = pd.read_csv(path, dtype=str, nrows=nrows, keep_default_na=False, na_values=[""])
        except UnicodeDecodeError:
            df = pd.read_csv(path, dtype=str, nrows=nrows, encoding="latin-1",
                             keep_default_na=False, na_values=[""])
    else:
        df = pd.read_excel(path, sheet_name=sheet or 0, dtype=str, nrows=nrows)
    df.columns = [str(c).strip() for c in df.columns]
    return df


# --- Column detection -------------------------------------------------------
def _score_header(header: str, hints: list[str]) -> int:
    name = re.sub(r"[^a-z0-9 ]", " ", str(header).lower()).strip()
    name = re.sub(r"\s+", " ", name)
    best = 0
    for index, hint in enumerate(hints):
        weight = len(hints) - index  # earlier hints are stronger signals
        if name == hint:
            best = max(best, 100 + weight)
        elif name.replace(" ", "") == hint.replace(" ", ""):
            best = max(best, 95 + weight)
        elif hint in name:
            best = max(best, 70 + weight)
        elif name in hint and len(name) >= 4:
            best = max(best, 60 + weight)
    return best


def _email_density(series: pd.Series) -> float:
    values = [str(v).strip() for v in series.dropna().head(50) if str(v).strip()]
    if not values:
        return 0.0
    hits = sum(1 for v in values if EMAIL_RE.match(v))
    return hits / len(values)


def detect_columns(df: pd.DataFrame) -> ColumnMapping:
    """Best-guess mapping. Header names first, cell content as the tie-breaker."""
    headers = list(df.columns)
    mapping = ColumnMapping()

    # Email: content wins over header names, since it is unambiguous
    densities = {h: _email_density(df[h]) for h in headers}
    best_density = max(densities.values(), default=0.0)
    if best_density >= 0.5:
        mapping.email = max(densities, key=densities.get)
    else:
        scored = [(h, _score_header(h, EMAIL_HINTS)) for h in headers]
        best = max(scored, key=lambda x: x[1], default=(None, 0))
        mapping.email = best[0] if best[1] >= 60 else None

    for attr, hints in (("company", COMPANY_HINTS), ("person", PERSON_HINTS)):
        candidates = [
            (h, _score_header(h, hints)) for h in headers
            if h not in {mapping.email, mapping.company, mapping.person}
        ]
        best = max(candidates, key=lambda x: x[1], default=(None, 0))
        if best[1] >= 60:
            setattr(mapping, attr, best[0])

    chosen = {mapping.email, mapping.company, mapping.person}
    mapping.extras = [h for h in headers if h not in chosen]
    return mapping


# --- Validation -------------------------------------------------------------
def validate_email(email: str) -> tuple[bool, str]:
    email = (email or "").strip()
    if not email:
        return False, "empty"
    if " " in email:
        return False, "contains a space"
    if email.count("@") != 1:
        return False, "must contain exactly one @"
    if not EMAIL_RE.match(email):
        return False, "not a valid address format"
    domain = email.split("@", 1)[1].lower()
    if domain in TYPO_DOMAINS:
        return False, f"likely typo, did you mean {TYPO_DOMAINS[domain]}?"
    if domain.endswith("."):
        return False, "domain ends with a dot"
    return True, ""


def risk_flags(email: str) -> list[str]:
    flags = []
    local = email.split("@", 1)[0].lower()
    if local in ROLE_PREFIXES or local.split("+")[0] in ROLE_PREFIXES:
        flags.append("role-account")
    if len(local) <= 2:
        flags.append("very-short-mailbox")
    return flags


# --- Import -----------------------------------------------------------------
# Rows per write transaction. SQLite allows one writer at a time, so a batch
# that takes milliseconds keeps the lock for milliseconds, and the UI thread
# never waits on it for long.
COMMIT_EVERY = 250


def domains_in(df: pd.DataFrame, column: str) -> list[str]:
    """Every distinct mail domain in the sheet, in the order they first appear."""
    domains: list[str] = []
    seen: set[str] = set()
    for value in df[column] if column in df.columns else []:
        text = str(value).strip().lower() if value is not None else ""
        if "@" not in text:
            continue
        domain = text.split("@", 1)[1]
        if domain and domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def resolve_domains(domains: list[str], progress=None, cancelled=None) -> dict[str, bool]:
    """Look up every domain's mail server up front, before any database work.

    This is the slow part of an import: one DNS round trip per domain, and a
    dead domain waits for a timeout. Doing it here, outside any transaction,
    is what keeps the write lock short.
    """
    from app.core import dns_tools

    answers: dict[str, bool] = {}
    for index, domain in enumerate(domains):
        if cancelled is not None and cancelled():
            break
        if progress:
            progress(index, len(domains))
        answers[domain] = dns_tools.has_mx(domain)
    if progress:
        progress(len(domains), len(domains))
    return answers


def import_dataframe(
    df: pd.DataFrame,
    mapping: ColumnMapping,
    source_file: str = "",
    check_mx: bool = True,
    progress=None,
    mx_answers: dict[str, bool] | None = None,
) -> ImportResult:
    """Insert/update contacts. Existing addresses keep their send history.

    ``mx_answers`` lets the caller do the DNS lookups first, which is what the
    import worker does. Without it the lookups happen here, still outside the
    write transactions.
    """
    result = ImportResult(total_rows=len(df))
    if not mapping.email:
        result.problems.append(("", "No email column selected"))
        return result

    from app.core import dns_tools  # imported lazily; DNS work is optional

    seen: set[str] = set()
    conn = db.connect()
    stamp = datetime.now().isoformat(timespec="seconds")
    mx_cache: dict[str, bool] = dict(mx_answers or {})
    pending = 0

    for position, (_, row) in enumerate(df.iterrows()):
        if progress and position % 25 == 0:
            progress(position, len(df))

        # Commit as we go. Holding one transaction for the whole import is what
        # used to block the UI thread's own writes until it timed out.
        if pending >= COMMIT_EVERY:
            conn.commit()
            pending = 0

        raw_email = row.get(mapping.email)
        email = str(raw_email).strip().lower() if raw_email is not None else ""
        if not email or email == "nan":
            result.invalid += 1
            continue

        if email in seen:
            result.duplicates += 1
            continue
        seen.add(email)

        ok, reason = validate_email(email)
        if not ok:
            result.invalid += 1
            result.problems.append((email, reason))
            continue

        if db.is_suppressed(email):
            result.suppressed += 1
            continue

        domain = email.split("@", 1)[1]
        if check_mx:
            if domain not in mx_cache:
                mx_cache[domain] = dns_tools.has_mx(domain)
            if not mx_cache[domain]:
                result.no_mx += 1
                result.problems.append((email, f"{domain} has no mail server (MX)"))
                continue

        flags = risk_flags(email)
        if flags:
            result.risky += 1

        company = str(row.get(mapping.company) or "").strip() if mapping.company else ""
        person = str(row.get(mapping.person) or "").strip() if mapping.person else ""
        extras = {}
        for column in mapping.extras:
            value = row.get(column)
            text = str(value).strip() if value is not None else ""
            if text and text.lower() != "nan":
                extras[column] = text

        existing = conn.execute("SELECT id FROM contacts WHERE email = ?", (email,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE contacts SET company = COALESCE(NULLIF(?, ''), company), "
                "person = COALESCE(NULLIF(?, ''), person), extra_json = ?, risk_flags = ?, valid = 1 "
                "WHERE id = ?",
                (company, person, json.dumps(extras) if extras else None,
                 ",".join(flags) if flags else None, existing["id"]),
            )
            result.updated += 1
            pending += 1
        else:
            conn.execute(
                "INSERT INTO contacts(email, company, person, extra_json, source_file, imported_at, "
                "valid, risk_flags) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (email, company or None, person or None,
                 json.dumps(extras) if extras else None, source_file, stamp,
                 ",".join(flags) if flags else None),
            )
            result.imported += 1
            pending += 1

    conn.commit()
    if progress:
        progress(len(df), len(df))
    db.log_event("info", "import", f"{source_file}: {result.summary()}")
    return result


def import_file(
    path: str | Path,
    sheet: str | None = None,
    mapping: ColumnMapping | None = None,
    check_mx: bool = True,
    progress=None,
) -> tuple[ImportResult, ColumnMapping]:
    df = read_sheet(path, sheet)
    mapping = mapping or detect_columns(df)
    result = import_dataframe(df, mapping, source_file=Path(path).name,
                              check_mx=check_mx, progress=progress)
    return result, mapping


# --- Queries ----------------------------------------------------------------
def contact_count(valid_only: bool = True) -> int:
    sql = "SELECT COUNT(*) AS n FROM contacts"
    if valid_only:
        sql += " WHERE valid = 1"
    row = db.query_one(sql)
    return row["n"] if row else 0


def list_contacts(limit: int = 500, offset: int = 0, search: str = "") -> list:
    if search:
        like = f"%{search}%"
        return db.query(
            "SELECT * FROM contacts WHERE email LIKE ? OR company LIKE ? OR person LIKE ? "
            "ORDER BY id LIMIT ? OFFSET ?",
            (like, like, like, limit, offset),
        )
    return db.query("SELECT * FROM contacts ORDER BY id LIMIT ? OFFSET ?", (limit, offset))


def merge_tag_names() -> list[str]:
    """Built-in tags plus every extra column seen in imported contacts."""
    from app.core.merge import BUILTIN_TAGS

    names = list(BUILTIN_TAGS)
    for row in db.query("SELECT DISTINCT extra_json FROM contacts WHERE extra_json IS NOT NULL LIMIT 200"):
        try:
            for key in json.loads(row["extra_json"]):
                if key not in names:
                    names.append(key)
        except (json.JSONDecodeError, TypeError):
            continue
    return names
