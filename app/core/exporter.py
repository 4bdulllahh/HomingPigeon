"""Export results back to Excel. Source spreadsheets are never modified."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from app import config
from app.core import db

STATUS_LABELS = {
    "pending": "Pending",
    "retry": "Will retry",
    "sent": "Sent",
    "failed": "Failed",
    "bounced": "Bounced",
    "skipped": "Skipped",
}


def _rows(campaign_id: int | None) -> list:
    if campaign_id:
        return db.query(
            "SELECT c.email, c.company, c.person, c.extra_json, c.risk_flags, c.replied_at, "
            "r.status, r.attempts, r.subject_used, r.sent_at, r.last_error "
            "FROM campaign_recipients r JOIN contacts c ON c.id = r.contact_id "
            "WHERE r.campaign_id = ? ORDER BY r.rowid",
            (campaign_id,),
        )
    return db.query(
        "SELECT c.email, c.company, c.person, c.extra_json, c.risk_flags, c.replied_at, "
        "NULL AS status, 0 AS attempts, NULL AS subject_used, NULL AS sent_at, NULL AS last_error "
        "FROM contacts c ORDER BY c.id"
    )


def build_dataframe(campaign_id: int | None = None) -> pd.DataFrame:
    records = []
    for row in _rows(campaign_id):
        record = {
            "Company": row["company"] or "",
            "Contact Person": row["person"] or "",
            "Email": row["email"],
            "Status": STATUS_LABELS.get(row["status"], row["status"] or ""),
            "Sent At": row["sent_at"] or "",
            "Subject Used": row["subject_used"] or "",
            "Attempts": row["attempts"] or 0,
            "Replied": "Yes" if row["replied_at"] else "",
            "Risk Flags": row["risk_flags"] or "",
            "Error": row["last_error"] or "",
        }
        if row["extra_json"]:
            try:
                for key, value in json.loads(row["extra_json"]).items():
                    record.setdefault(key, value)
            except (json.JSONDecodeError, TypeError):
                pass
        records.append(record)
    return pd.DataFrame(records)


def export_campaign(campaign_id: int | None = None, path: str | Path | None = None) -> Path:
    df = build_dataframe(campaign_id)

    if path is None:
        config.ensure_dirs()
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        name = f"campaign_{campaign_id}_{stamp}.xlsx" if campaign_id else f"contacts_{stamp}.xlsx"
        path = Path(config.EXPORTS_DIR) / name
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")
        sheet = writer.sheets["Results"]
        for index, column in enumerate(df.columns, start=1):
            longest = max([len(str(column))] + [len(str(v)) for v in df[column].head(200)])
            sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = \
                min(max(12, longest + 2), 55)
        sheet.freeze_panes = "A2"

    db.log_event("info", "export", f"Exported {len(df)} rows to {path.name}")
    return path


def export_suppression(path: str | Path | None = None) -> Path:
    rows = db.suppression_list()
    df = pd.DataFrame([
        {"Email": r["email"], "Reason": r["reason"], "Source": r["source"], "Added": r["added_at"]}
        for r in rows
    ])
    if path is None:
        config.ensure_dirs()
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = Path(config.EXPORTS_DIR) / f"suppression_{stamp}.xlsx"
    path = Path(path)
    df.to_excel(path, index=False, sheet_name="Suppression")
    return path


def import_suppression(path: str | Path) -> int:
    """Bulk-load a do-not-contact list from CSV or Excel."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str)
    else:
        df = pd.read_excel(path, dtype=str)

    column = next((c for c in df.columns if "mail" in str(c).lower()), df.columns[0])
    added = 0
    for value in df[column].dropna():
        email = str(value).strip().lower()
        if "@" in email:
            db.suppress(email, "Imported do-not-contact list", source="import")
            added += 1
    return added
