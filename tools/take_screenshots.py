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

    # Written the way the built-in examples are: short, personal, no links, one
    # question, unsubscribe line off. That is what scores well and reaches the
    # main inbox, so it is what the My message screenshot shows.
    db.set_setting("unsubscribe_note", False)
    db.set_setting("attach_mode", "none")
    set_id = db.execute("INSERT INTO template_sets (name, signature_html, created_at) VALUES (?, ?, ?)",
                        ("Autumn outreach",
                         "Jamie Reed\nFounder, Sparrow Supplies\nPhone: +44 113 496 0000\n"
                         "12 Mill Street, Leeds, UK", db.now()))
    db.set_setting("template_set_id", set_id)
    for position, text in enumerate(["{Quick question|A question} about {{Company}}",
                                     "{{FirstName}}, {a quick question|one question} for you",
                                     "Packaging for the team at {{Company}}"]):
        db.execute("INSERT INTO subjects (set_id, text, position) VALUES (?, ?, ?)", (set_id, text, position))
    bodies = [
        ("Short and friendly", "\n\n".join([
            "{Hi|Hello} {{FirstName}},",
            "I came across {{Company}} while looking at independent businesses in {{City}}, and "
            "I wanted to get in touch personally.",
            "I run Sparrow Supplies, a small team making compostable packaging for shops like "
            "yours. Most of the people we work with came to us because plastic wrapping was "
            "costing them more than it should, in money and in customer goodwill.",
            "Would it be useful if I posted a few samples over to you next week?",
            "{Thanks|Many thanks},"])),
        ("With a question", "\n\n".join([
            "{Hi|Hello} {{FirstName}},",
            "I hope you do not mind me writing to you directly. I work at Sparrow Supplies, "
            "where we make plastic-free packaging for businesses like {{Company}}.",
            "A cafe similar to yours told us recently that switching away from plastic took far "
            "more of their time than it should. We sorted that out for them within a few weeks.",
            "Is that something you are thinking about at {{Company}} as well?",
            "{Best wishes|Kind regards},"])),
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
    db.backfill_contacted(connection)
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


def demo_pictures() -> tuple[dict, dict]:
    """A logo and a photo-like picture for the Email design screenshot, drawn here."""
    import io

    from PIL import Image, ImageDraw, ImageFilter

    from app.core import design

    folder = Path(tempfile.mkdtemp(prefix="hp-pictures-"))
    logo = Image.new("RGBA", (520, 120), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logo)
    draw.ellipse((6, 10, 106, 110), fill="#e8793a")
    draw.polygon([(30, 70), (86, 38), (70, 84)], fill="#ffffff")
    draw.text((126, 60), "Sparrow Supplies", fill="#1f2530", font=design._font(46), anchor="lm")
    logo.save(folder / "logo.png")

    photo = Image.new("RGB", (1200, 680), "#f3d9c4")
    draw = ImageDraw.Draw(photo)
    for y in range(680):
        shade = int(232 - y * 0.06)
        draw.line([(0, y), (1200, y)], fill=(shade, int(shade * 0.86), int(shade * 0.74)))
    draw.rectangle((0, 470, 1200, 680), fill="#c9a27e")
    for x, w, h, colour in ((170, 300, 230, "#d8b48c"), (500, 240, 300, "#e9cfa9"),
                            (770, 280, 190, "#cfa57a")):
        draw.rounded_rectangle((x, 520 - h, x + w, 540), radius=10, fill=colour)
        draw.line([(x + w // 2, 520 - h), (x + w // 2, 540)], fill="#b98b5e", width=6)
    draw.ellipse((940, 70, 1080, 210), fill="#fff4e0")
    photo = photo.filter(ImageFilter.GaussianBlur(1.2))
    out = io.BytesIO()
    photo.save(out, "JPEG", quality=90)
    (folder / "photo.jpg").write_bytes(out.getvalue())
    return design.prepare_image(folder / "logo.png"), design.prepare_image(folder / "photo.jpg")


def demo_design() -> int:
    """A finished-looking design for the Email design screenshot. Returns its id."""
    from app.core import design

    logo, photo = demo_pictures()
    design.save_brand_kit({"primary": "#e8793a", "text": "#2b2f36", "background": "#f6efe8",
                           "font": "Helvetica", "logo": logo})
    data = design.starter("welcome")
    data["page"].update(bg="#f6efe8", bg2="#e6d9f2")
    for block in data["blocks"]:
        if block["type"] == "heading":
            block["text"] = "A greener way to pack, {{FirstName}}"
        elif block["type"] == "image":
            block["image"] = design.add_asset(data, photo)
        elif block["type"] == "button":
            block["label"] = "Request free samples"
        elif block["type"] == "footer":
            block["text"] = "Sparrow Supplies\n12 Mill Street, Leeds, UK"
    social = design.new_block("social", design.brand_kit())
    social.update(linkedin="linkedin.com/company/sparrow", instagram="instagram.com/sparrow",
                  website="sparrowsupplies.example")
    data["blocks"].insert(len(data["blocks"]) - 1, social)
    return design.save(data, "Spring samples")


def main() -> int:
    from app import config

    data = Path(tempfile.mkdtemp(prefix="hp-screens-"))
    real = config.DATA_DIR
    for name in ("DB_PATH", "SECRETS_PATH", "KEYS_DIR", "EXPORTS_DIR", "LOGS_DIR"):
        setattr(config, name, data / getattr(config, name).relative_to(real))
    config.DATA_DIR = data
    config.DESIGNS_DIR = data / "Designs"

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QScrollArea

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from app.core import db

    db.init()
    fill_demo_data()
    design_id = demo_design()
    db.set_setting("text_size", "medium")

    from app.ui import theme
    from app.ui.main_window import MainWindow

    OUT.mkdir(parents=True, exist_ok=True)
    prefs_appearance = [None]

    def settle(ms: int = 600) -> None:
        end = datetime.now() + timedelta(milliseconds=ms)
        while datetime.now() < end:
            app.processEvents()

    # (page, file name, tab, appearance): the eight README pictures
    shots = [("dashboard", "home", None, "Dark"), ("contacts", "contacts", "My contacts", "Dark"),
             ("templates", "spam-score", "Preview & score", "Dark"), ("design", "design", None, "Dark"),
             ("campaign", "warmup", None, "Dark"), ("send", "send", None, "Dark"),
             ("settings", "themes", None, "midnight")]
    window = None
    for key, name, tab, appearance in shots:
        if window is None or appearance != prefs_appearance[0]:
            if window is not None:
                window.close()
                settle(200)
            db.set_setting("appearance", appearance)
            prefs_appearance[0] = appearance
            theme.apply_preferences()
            app.setStyleSheet(theme.stylesheet())
            window = MainWindow()
            window.resize(*SIZE)
            window.show()
            settle(1200)
        if name == "design":
            # Switched on only now, so the score shot shows the plain email
            from app.core import design

            design.set_active(design_id)
        window.show_page(key)
        if tab:
            window.page(key).tabs.set(tab)
        page = window.page(key)
        if name == "design":
            page._open(design_id)
            settle(800)
            # The picture, so the shot shows its resize handle and the toolbar
            picture = next(b for b in page._design["blocks"] if b["type"] == "image")
            page._select(picture["id"])
        elif key == "campaign":
            settle(400)
            scroll = page.findChild(QScrollArea)
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        settle(2500 if tab else 600)
        path = OUT / f"{name}.png"
        window.grab().save(str(path))
        print(f"saved {path.relative_to(ROOT)}")
    window.close()
    settle(200)

    # The same app in other languages: Arabic reads right to left
    from app import i18n

    db.set_setting("appearance", "Dark")
    theme.apply_preferences()
    app.setStyleSheet(theme.stylesheet())
    for code, key, name in (("ar", "dashboard", "home-arabic"),):
        i18n.set_language(code)
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if i18n.is_rtl()
                               else Qt.LayoutDirection.LeftToRight)
        window = MainWindow()
        window.resize(*SIZE)
        window.show()
        settle(1200)
        window.show_page(key)
        settle(800)
        path = OUT / f"{name}.png"
        window.grab().save(str(path))
        print(f"saved {path.relative_to(ROOT)}")
        window.close()
        settle(200)
    i18n.set_language("en")
    app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
