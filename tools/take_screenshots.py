"""Render the README screenshots into docs/screenshots/.

    python tools/take_screenshots.py

The app runs against a throwaway data folder filled with made-up businesses on
.example addresses, so no real contact list or account ever appears in an
image. Nothing is sent and nothing on the network is contacted.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "screenshots"
SIZE = (1440, 900)

COMPANIES = [
    ("Bright Crumb Bakery", "Maya Torres"), ("Northwind Joinery", "Sam Okafor"),
    ("Harbour Lane Florists", "Priya Nair"), ("Copperleaf Studio", "Leo Brandt"),
    ("Tidewater Cafe", "Ana Ruiz"), ("Summit Print Co", "Omar Haddad"),
    ("Blue Kettle Catering", "Grace Lin"), ("Oakridge Dental", "Tom Fischer"),
    ("Lantern Street Books", "Hana Sato"), ("Meadowbrook Farm Shop", "Ivan Petrov"),
    ("Greenline Cycles", "Zara Ahmed"), ("Silverfin Seafood", "Noah Clarke"),
    ("Pebble & Pine Interiors", "Elena Rossi"), ("Riverside Tailors", "Kwame Mensah"),
    ("Juniper Yoga", "Chloe Martin"), ("Foxglove Pottery", "Arjun Mehta"),
    ("Keystone Plumbing", "Lucy Evans"), ("Morningside Vets", "Diego Alvarez"),
]


def slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def fill_demo_data() -> None:
    from app.core import db

    db.set_setting("sender_name", "Jamie from Sparrow Supplies")
    db.set_setting("sender_email", "jamie@sparrowsupplies.example")
    db.set_setting("reply_to", "jamie@sparrowsupplies.example")
    db.set_setting("smtp_host", "smtp.sparrowsupplies.example")
    db.set_setting("smtp_username", "jamie@sparrowsupplies.example")
    db.set_setting("imap_host", "imap.sparrowsupplies.example")
    db.set_setting("link_url", "https://sparrowsupplies.example/brochure")

    now = datetime.now()
    rows = []
    for index, (company, person) in enumerate(COMPANIES * 3):
        suffix = "" if index < len(COMPANIES) else str(index // len(COMPANIES) + 1)
        email = f"{person.split()[0].lower()}{suffix}@{slug(company)}.example"
        imported = (now - timedelta(days=3, minutes=index)).isoformat(timespec="seconds")
        rows.append((email, company, person, json.dumps({"City": ["Leeds", "Bristol", "York"][index % 3]}),
                     "leads-autumn.xlsx", imported, 1, ""))
    db.execute_many("INSERT INTO contacts (email, company, person, extra_json, source_file, "
                    "imported_at, valid, risk_flags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

    set_id = db.execute("INSERT INTO template_sets (name, signature_html, created_at) VALUES (?, ?, ?)",
                        ("Autumn outreach", "<p>Jamie Reed<br>Sparrow Supplies</p>", db.now()))
    db.set_setting("template_set_id", set_id)
    for position, text in enumerate(["Packaging for {{Company}}?", "A quick idea for {{Company}}",
                                     "{{FirstName}}, eco packaging samples"]):
        db.execute("INSERT INTO subjects (set_id, text, position) VALUES (?, ?, ?)", (set_id, text, position))
    bodies = [
        ("Short and friendly",
         "<p>Hi {{FirstName}},</p><p>I run Sparrow Supplies, a small team making compostable "
         "packaging for independent shops like {{Company}}. Would a free box of samples be "
         "useful?</p><p>Happy to send some over this week.</p>"),
        ("With a question",
         "<p>Hello {{FirstName}},</p><p>Do you still wrap orders at {{Company}} in plastic? We "
         "make plastic-free packaging that costs about the same, and I'd love to send you a few "
         "samples to try.</p>"),
    ]
    for position, (name, html) in enumerate(bodies):
        db.execute("INSERT INTO bodies (set_id, name, html, position) VALUES (?, ?, ?, ?)",
                   (set_id, name, html, position))

    campaign = db.execute("INSERT INTO campaigns (name, status, template_set_id, created_at, started_at) "
                          "VALUES (?, ?, ?, ?, ?)", ("Autumn outreach", "paused", set_id, db.now(), db.now()))
    contacts = db.query("SELECT id, email, company FROM contacts ORDER BY id LIMIT 40")
    statuses = ["sent"] * 40
    statuses[10], statuses[29] = "bounced", "failed"
    for index, (contact, status) in enumerate(zip(contacts, statuses)):
        sent_at = (now - timedelta(hours=26, minutes=-index * 2)).isoformat(timespec="seconds")
        db.execute("INSERT INTO campaign_recipients (campaign_id, contact_id, status, attempts, "
                   "subject_used, body_variant, sent_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
                   (campaign, contact["id"], status,
                    [f"Packaging for {contact['company']}?",
                     f"A quick idea for {contact['company']}"][index % 2],
                    bodies[index % 2][0], sent_at))
    db.execute("UPDATE contacts SET replied_at = ? WHERE id IN (?, ?)",
               (db.now(), contacts[1]["id"], contacts[4]["id"]))
    # The Sent emails page reads the permanent history, filled the same way an upgrade does
    connection = db.connect()
    db.backfill_sent_log(connection)
    connection.commit()
    db.suppress(contacts[10]["email"], "Hard bounce: mailbox does not exist", "imap")

    replies = [
        (contacts[1], "Re: A quick idea for Northwind Joinery",
         "Hi Jamie, yes please, send a box over. We ship about 40 orders a week. Sam"),
        (contacts[4], "Re: A quick idea for Tidewater Cafe",
         "Sounds good. Could you include the price list too? Thanks, Ana"),
        (contacts[10], "Undelivered Mail Returned to Sender",
         "This is the mail system. The address could not be delivered: mailbox does not exist."),
    ]
    for uid, (contact, subject, body) in enumerate(replies, start=1):
        kind = "bounce" if "Undelivered" in subject else "reply"
        db.save_message("INBOX", uid, from_name=contact["email"].split("@")[0].title(),
                        from_email=contact["email"], subject=subject, body=body, kind=kind, known=True,
                        received_at=(now - timedelta(hours=uid * 3)).isoformat(timespec="seconds"))

    db.execute("INSERT OR REPLACE INTO warmup_state (id, started_on, day_index, sent_date, sent_today) "
               "VALUES (1, ?, 9, ?, 14)", ((now - timedelta(days=9)).date().isoformat(),
                                            now.date().isoformat()))
    for level, category, message in [
            ("info", "import", "Imported 54 contacts from leads-autumn.xlsx"),
            ("info", "send", "Sent 14 emails today, the warm-up limit for day 9"),
            ("warn", "inbox", "Removed 1 address that bounced"),
            ("success", "inbox", "2 people replied")]:
        db.log_event(level, category, message)


def main() -> int:
    from app import config

    data = Path(tempfile.mkdtemp(prefix="hp-screens-"))
    real = config.DATA_DIR
    for name in ("DB_PATH", "SECRETS_PATH", "KEYS_DIR", "EXPORTS_DIR", "LOGS_DIR"):
        setattr(config, name, data / getattr(config, name).relative_to(real))
    config.DATA_DIR = data

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from app.core import db

    db.init()
    fill_demo_data()
    db.set_setting("text_size", "medium")

    from app.ui import theme
    from app.ui.main_window import MainWindow

    OUT.mkdir(parents=True, exist_ok=True)

    def settle(ms: int = 600) -> None:
        end = datetime.now() + timedelta(milliseconds=ms)
        while datetime.now() < end:
            app.processEvents()

    shots = [("dashboard", "home", None), ("guide", "start-here", None),
             ("contacts", "contacts", "My contacts"), ("templates", "templates", "Preview & score"),
             ("send", "send", None), ("sent", "sent", None), ("inbox", "inbox", None),
             ("deliverability", "deliverability", "SPF generator"), ("settings", "settings", None)]
    for appearance in ("Dark", "Light"):
        db.set_setting("appearance", appearance)
        theme.apply_preferences()
        app.setStyleSheet(theme.stylesheet())
        window = MainWindow()
        window.resize(*SIZE)
        window.show()
        settle(1200)
        for key, name, tab in shots if appearance == "Dark" else shots[:1]:
            window.show_page(key)
            if tab:
                window.page(key).tabs.set(tab)
            settle(2500 if tab else 600)
            path = OUT / f"{name}-{appearance.lower()}.png"
            window.grab().save(str(path))
            print(f"saved {path.relative_to(ROOT)}")

        if appearance == "Dark":
            from app.services import updater
            from app.ui.widgets.update_dialog import UpdateDialog

            release = updater.Release(
                tag="v0.7.0", page_url=f"{config.REPO_URL}/releases",
                notes="* Faster imports\n* A new template for follow-ups\n* Fixes for the inbox")
            updater.can_update_itself = lambda _release=None: True   # show the installed wording
            dialog = UpdateDialog(window, release)
            dialog.show()
            settle()
            path = OUT / "update-popup.png"
            dialog.grab().save(str(path))
            print(f"saved {path.relative_to(ROOT)}")
            dialog.close()
        window.close()
        settle(200)

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
