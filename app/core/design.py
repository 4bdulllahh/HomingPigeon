"""Email designs: the frame around the message.

A design is page styling plus a list of blocks (logo, heading, picture,
button...). The "Your message" block marks where each person's message goes,
so the several versions and the {a|b} mixing keep doing their anti-spam work
inside a designed email.

Designs are stored as JSON in the designs table. Pictures live inside the
design (base64), so a design file exported on one PC opens on another, and they
travel inside the email as inline parts (cid:), which every email program shows
without the sender needing a website.

The HTML is built from tables with inline styles: the only layout that Gmail,
Outlook and Apple Mail all agree on.
"""
from __future__ import annotations

import base64
import copy
import html
import io
import json
import random
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.core import composer, db, merge
from app.i18n import t

# --- what a design is made of -------------------------------------------------


@dataclass(frozen=True)
class Field:
    """One setting of a block or of the page, as the editor shows it."""
    key: str
    label: str
    kind: str                  # text, multiline, code, color, number, choice, bool, image, url, font
    default: Any = ""
    options: tuple = ()        # (value, label) pairs for a choice
    low: int = 0
    high: int = 100
    suffix: str = "px"
    section: str = "Content"
    brand: str = ""            # brand-kit colour this follows: primary, text, background
    optional: bool = False     # a colour that may be left empty
    note: str = ""


@dataclass(frozen=True)
class BlockSpec:
    kind: str
    label: str
    group: str
    glyph: str
    note: str
    fields: tuple


# Fonts every email program has. Anything else falls back to these anyway.
FONTS = {
    "Arial": "Arial,Helvetica,sans-serif",
    "Helvetica": "Helvetica,Arial,sans-serif",
    "Verdana": "Verdana,Geneva,sans-serif",
    "Tahoma": "Tahoma,Verdana,sans-serif",
    "Trebuchet MS": "'Trebuchet MS',Arial,sans-serif",
    "Segoe UI": "'Segoe UI',Arial,sans-serif",
    "Georgia": "Georgia,'Times New Roman',serif",
    "Times New Roman": "'Times New Roman',Times,serif",
    "Palatino": "'Palatino Linotype',Palatino,serif",
    "Courier New": "'Courier New',Courier,monospace",
}

# Social networks: label, brand colour and the letters drawn on the icon
NETWORKS = {
    "linkedin": ("LinkedIn", "#0a66c2", "in"),
    "facebook": ("Facebook", "#1877f2", "f"),
    "instagram": ("Instagram", "#e1306c", "IG"),
    "x": ("X", "#111111", "X"),
    "youtube": ("YouTube", "#ff0000", "YT"),
    "tiktok": ("TikTok", "#111111", "TT"),
    "whatsapp": ("WhatsApp", "#25d366", "WA"),
    "website": ("Website", "#555555", "www"),
}

ALIGN = (("left", "Left"), ("center", "Centre"), ("right", "Right"))
SPACING = "Spacing and background"

COMMON = (
    Field("bg", "Background colour", "color", "", section=SPACING, optional=True),
    Field("pad_top", "Space above", "number", 8, low=0, high=120, section=SPACING),
    Field("pad_bottom", "Space below", "number", 8, low=0, high=120, section=SPACING),
    Field("pad_side", "Space at the sides", "number", 32, low=0, high=120, section=SPACING),
)


def _column_fields(side: str, title: str) -> tuple:
    section = "Left column" if side == "left" else "Right column"
    return (
        Field(f"{side}_image", "Picture", "image", section=section),
        Field(f"{side}_title", "Title", "text", title, section=section),
        Field(f"{side}_text", "Text", "multiline", "[A sentence or two about it]", section=section),
        Field(f"{side}_button", "Button words", "text", "", section=section,
              note="Leave empty for no button."),
        Field(f"{side}_url", "Button link", "url", "", section=section),
    )


BLOCKS: dict[str, BlockSpec] = {spec.kind: spec for spec in (
    # Text
    BlockSpec("heading", "Heading", "Text", "H", "A big title.", (
        Field("text", "Words", "text", "[Your heading]"),
        Field("size", "Size", "number", 26, low=14, high=64, section="Style"),
        Field("color", "Colour", "color", "#1f2530", section="Style", brand="text"),
        Field("align", "Alignment", "choice", "left", ALIGN, section="Style"),
        Field("weight", "Thickness", "choice", "bold",
              (("bold", "Bold"), ("normal", "Normal")), section="Style"),
        Field("font", "Font", "font", "", section="Style",
              note="Leave on 'Same as the email' to use the email's font."),
    )),
    BlockSpec("message", "Your message", "Text", "✉",
              "Where your message goes. Each person gets one of the messages you wrote on "
              "the My message page here, with your signature underneath.", (
                  Field("align", "Alignment", "choice", "left", ALIGN, section="Style"),
                  Field("size", "Text size", "number", 15, low=11, high=24, section="Style"),
                  Field("color", "Colour", "color", "#333333", section="Style", brand="text"),
                  Field("signature", "Add my signature underneath", "bool", True,
                        section="Style"),
              )),
    BlockSpec("text", "Text", "Text", "¶", "A paragraph of your own words.", (
        Field("text", "Words", "multiline", "[Write something here]",
              note="Type it like a normal email. {{FirstName}} and {Hi|Hello} work here too."),
        Field("size", "Text size", "number", 15, low=11, high=28, section="Style"),
        Field("color", "Colour", "color", "#333333", section="Style", brand="text"),
        Field("align", "Alignment", "choice", "left", ALIGN, section="Style"),
        Field("italic", "Italic", "bool", False, section="Style"),
    )),
    BlockSpec("quote", "Quote", "Text", "❝", "A quote or testimonial with a coloured bar.", (
        Field("text", "Quote", "multiline", "[What a happy customer said about you]"),
        Field("author", "Who said it", "text", ""),
        Field("bar", "Bar colour", "color", "#2f7fd8", section="Style", brand="primary"),
        Field("color", "Text colour", "color", "#333333", section="Style", brand="text"),
        Field("size", "Text size", "number", 16, low=11, high=28, section="Style"),
        Field("italic", "Italic", "bool", True, section="Style"),
    )),
    BlockSpec("links", "Links row", "Text", "⋯", "A row of small links, like a menu.", (
        Field("items", "Links", "multiline",
              "[Our website] | www.yourcompany.com\n[Contact us] | www.yourcompany.com/contact",
              note="One link per line: the words, a straight line |, then the web address."),
        Field("color", "Colour", "color", "#2f7fd8", section="Style", brand="primary"),
        Field("size", "Text size", "number", 13, low=10, high=20, section="Style"),
        Field("align", "Alignment", "choice", "right", ALIGN, section="Style"),
        Field("underline", "Underline the links", "bool", True, section="Style"),
    )),
    # Pictures
    BlockSpec("logo", "Logo", "Pictures", "◎", "Your logo, usually at the top.", (
        Field("image", "Logo picture", "image"),
        Field("width", "Width", "number", 140, low=30, high=400, section="Style"),
        Field("align", "Alignment", "choice", "center", ALIGN, section="Style"),
        Field("link", "Opens this web address when clicked", "url", ""),
        Field("alt", "Words shown if pictures are blocked", "text", "[Your company]"),
    )),
    BlockSpec("banner", "Banner", "Pictures", "▬",
              "A wide picture or a coloured band with a headline.", (
                  Field("image", "Wide picture", "image",
                        note="Leave empty for a coloured band instead."),
                  Field("title", "Headline", "text", "[Your big headline]"),
                  Field("subtitle", "Line underneath", "text", "[One line that says more]"),
                  Field("color", "Band colour", "color", "#2f7fd8", section="Style",
                        brand="primary"),
                  Field("color2", "Second colour (fade)", "color", "", section="Style",
                        optional=True, note="Pick one to fade the band from one colour to "
                        "the other."),
                  Field("text_color", "Text colour", "color", "#ffffff", section="Style"),
                  Field("title_size", "Headline size", "number", 30, low=16, high=64, section="Style"),
                  Field("align", "Alignment", "choice", "center", ALIGN, section="Style"),
              )),
    BlockSpec("image", "Picture", "Pictures", "▣", "A photo or picture.", (
        Field("image", "Picture", "image"),
        Field("width", "Width", "number", 100, low=10, high=100, suffix="%", section="Style"),
        Field("align", "Alignment", "choice", "center", ALIGN, section="Style"),
        Field("radius", "Rounded corners", "number", 0, low=0, high=60, section="Style"),
        Field("link", "Opens this web address when clicked", "url", ""),
        Field("alt", "Words shown if pictures are blocked", "text", ""),
        Field("caption", "Caption underneath", "text", ""),
    )),
    BlockSpec("video", "Video", "Pictures", "▶",
              "A picture with a play button that opens your video. Email cannot play video "
              "itself, so people watch it on YouTube or your website.", (
                  Field("image", "Video thumbnail", "image"),
                  Field("url", "Video link", "url", ""),
                  Field("play", "Play button colour", "color", "#e02424", section="Style",
                        brand="primary"),
                  Field("width", "Width", "number", 100, low=20, high=100, suffix="%", section="Style"),
                  Field("align", "Alignment", "choice", "center", ALIGN, section="Style"),
                  Field("radius", "Rounded corners", "number", 8, low=0, high=60, section="Style"),
                  Field("alt", "Words shown if pictures are blocked", "text", "[Watch the video]"),
              )),
    # Actions
    BlockSpec("button", "Button", "Actions", "▭", "A coloured button with a link.", (
        Field("label", "Button words", "text", "[Book a call]"),
        Field("url", "Opens this web address", "url", ""),
        Field("color", "Button colour", "color", "#2f7fd8", section="Style", brand="primary"),
        Field("text_color", "Text colour", "color", "#ffffff", section="Style"),
        Field("radius", "Rounded corners", "number", 6, low=0, high=40, section="Style"),
        Field("size", "Size", "choice", "medium",
              (("small", "Small"), ("medium", "Medium"), ("large", "Large")), section="Style"),
        Field("align", "Alignment", "choice", "center", ALIGN, section="Style"),
        Field("full", "Full width", "bool", False, section="Style"),
        Field("border", "Border colour", "color", "", section="Style", optional=True),
    )),
    BlockSpec("social", "Social icons", "Actions", "◍",
              "Links to your social media pages. Empty ones are left out.", (
                  *(Field(key, label, "url", "", section="Links")
                    for key, (label, _colour, _letters) in NETWORKS.items()),
                  Field("style", "Look", "choice", "round",
                        (("round", "Round"), ("square", "Square"), ("text", "Words")),
                        section="Style"),
                  Field("colours", "Colours", "choice", "brand",
                        (("brand", "Each network's own"), ("one", "One colour")),
                        section="Style"),
                  Field("color", "Icon colour", "color", "#2f7fd8", section="Style",
                        brand="primary"),
                  Field("size", "Size", "number", 32, low=20, high=56, section="Style"),
                  Field("align", "Alignment", "choice", "center", ALIGN, section="Style"),
              )),
    # Layout
    BlockSpec("columns", "Two columns", "Layout", "◫",
              "Two things side by side, such as a picture and some words. On a phone they "
              "stack on top of each other.", (
                  *_column_fields("left", "[First title]"),
                  *_column_fields("right", "[Second title]"),
                  Field("ratio", "Widths", "choice", "50",
                        (("50", "Half and half"), ("33", "Narrow, wide"),
                         ("67", "Wide, narrow")), section="Style"),
                  Field("gap", "Space between", "number", 20, low=0, high=60, section="Style"),
                  Field("title_color", "Title colour", "color", "#1f2530", section="Style",
                        brand="text"),
                  Field("color", "Text colour", "color", "#555555", section="Style"),
                  Field("button_color", "Button colour", "color", "#2f7fd8", section="Style",
                        brand="primary"),
                  Field("align", "Alignment", "choice", "left", ALIGN, section="Style"),
              )),
    BlockSpec("card", "Card", "Layout", "▢",
              "A rounded box that makes something stand out, with an optional button.", (
                  Field("image", "Picture", "image"),
                  Field("title", "Title", "text", "[Something worth a look]"),
                  Field("text", "Text", "multiline", "[A few words about it]"),
                  Field("button", "Button words", "text", "",
                        note="Leave empty for no button."),
                  Field("url", "Button link", "url", ""),
                  Field("card_bg", "Box colour", "color", "#eef3f8", section="Style"),
                  Field("border", "Border colour", "color", "#d6dee8", section="Style",
                        optional=True),
                  Field("radius", "Rounded corners", "number", 12, low=0, high=40, section="Style"),
                  Field("inner", "Space inside", "number", 20, low=6, high=60, section="Style"),
                  Field("title_color", "Title colour", "color", "#1f2530", section="Style",
                        brand="text"),
                  Field("color", "Text colour", "color", "#555555", section="Style"),
                  Field("button_color", "Button colour", "color", "#2f7fd8", section="Style",
                        brand="primary"),
                  Field("align", "Alignment", "choice", "left", ALIGN, section="Style"),
              )),
    BlockSpec("divider", "Line", "Layout", "═", "A thin line between sections.", (
        Field("color", "Colour", "color", "#e3e7ee", section="Style"),
        Field("thickness", "Thickness", "number", 1, low=1, high=10, section="Style"),
        Field("width", "Width", "number", 100, low=10, high=100, suffix="%", section="Style"),
        Field("style", "Look", "choice", "solid",
              (("solid", "Solid"), ("dashed", "Dashes"), ("dotted", "Dots")), section="Style"),
    )),
    BlockSpec("spacer", "Empty space", "Layout", "↕", "Empty space between blocks.", (
        Field("height", "Height", "number", 24, low=4, high=200, section="Style"),
    )),
    # Footer and more
    BlockSpec("footer", "Footer", "Footer and more", "▁",
              "Small print at the bottom: your company name and address. The unsubscribe "
              "line goes here too when it is switched on.", (
                  Field("text", "Words", "multiline", "[Your company name]\n[Street, city, country]"),
                  Field("color", "Colour", "color", "#8a8f98", section="Style"),
                  Field("size", "Text size", "number", 12, low=9, high=16, section="Style"),
                  Field("align", "Alignment", "choice", "center", ALIGN, section="Style"),
              )),
    BlockSpec("html", "Your own HTML", "Footer and more", "‹›",
              "For people who know HTML. It is put in exactly as written.", (
                  Field("code", "HTML", "code", "<p>Hello</p>"),
              )),
)}

GROUPS = ("Text", "Pictures", "Actions", "Layout", "Footer and more")

PAGE_FIELDS = (
    Field("width", "Email width", "number", 600, low=360, high=800, section="Layout"),
    Field("position", "Email position", "choice", "center",
          (("center", "Centre"), ("left", "Left")), section="Layout"),
    Field("outer_pad", "Space around the email", "number", 24, low=0, high=80, section="Layout"),
    Field("bg", "Outside colour", "color", "#f4f5f7", section="Colours", brand="background"),
    Field("gradient", "Fade the outside", "choice", "none",
          (("none", "No fade"), ("down", "Top to bottom"), ("across", "Left to right"),
           ("diagonal", "Corner to corner")), section="Colours"),
    Field("bg2", "Second outside colour", "color", "#dfe7f2", section="Colours"),
    Field("card_bg", "Email colour", "color", "#ffffff", section="Colours"),
    Field("text", "Text colour", "color", "#333333", section="Colours", brand="text"),
    Field("link", "Link colour", "color", "#2f7fd8", section="Colours", brand="primary"),
    Field("radius", "Rounded corners", "number", 8, low=0, high=40, section="Shape"),
    Field("border", "Border colour", "color", "", section="Shape", optional=True),
    Field("shadow", "Soft shadow", "bool", False, section="Shape"),
    Field("font", "Font", "font", "Arial", section="Text"),
    Field("size", "Text size", "number", 15, low=12, high=20, section="Text"),
    Field("line", "Line spacing", "choice", "1.6",
          (("1.4", "Tight"), ("1.6", "Normal"), ("1.8", "Airy")), section="Text"),
    Field("preheader", "Inbox preview text", "text", "", section="Inbox",
          note="The grey line people see after the subject in their inbox. Leave empty to "
               "show the start of your message."),
)

DEFAULT_KIT = {"primary": "#2f7fd8", "text": "#333333", "background": "#f4f5f7",
               "font": "Arial", "logo": None}

MAX_IMAGE_WIDTH = 1200
MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_DESIGN_FILE = 40 * 1024 * 1024
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def page_defaults() -> dict:
    return {f.key: f.default for f in PAGE_FIELDS}


def fields_for(kind: str) -> tuple:
    """Every setting of a block: its own, then spacing and background."""
    spec = BLOCKS[kind]
    if kind == "spacer":
        return spec.fields + (COMMON[0],)
    return spec.fields + COMMON


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def brand_kit() -> dict:
    kit = dict(DEFAULT_KIT)
    saved = db.get_setting("brand_kit", None)
    if isinstance(saved, dict):
        for key in ("primary", "text", "background"):
            if isinstance(saved.get(key), str) and HEX.match(saved[key]):
                kit[key] = saved[key]
        if saved.get("font") in FONTS:
            kit["font"] = saved["font"]
        if _valid_asset(saved.get("logo")):
            kit["logo"] = saved["logo"]
    return kit


def save_brand_kit(kit: dict) -> None:
    db.set_setting("brand_kit", kit)


def new_block(kind: str, kit: dict | None = None, design: dict | None = None) -> dict:
    """A block with its default settings, coloured from the brand kit."""
    kit = kit or DEFAULT_KIT
    block = {"id": _new_id(), "type": kind}
    for field in fields_for(kind):
        if field.brand in ("primary", "text"):
            block[field.key] = kit[field.brand]
        elif field.kind in ("text", "multiline") and field.default:
            block[field.key] = t(field.default)     # placeholders in the user's language
        else:
            block[field.key] = field.default
    if kind == "links":
        block["items"] = example_links()
    if kind == "spacer":
        block["pad_top"] = block["pad_bottom"] = block["pad_side"] = 0
    if kind == "logo" and design is not None and kit.get("logo"):
        block["image"] = add_asset(design, kit["logo"])
    return block


def move_block(blocks: list, block: dict, index: int) -> bool:
    """Move ``block`` to land before whatever is at ``index`` now. False when nothing moves."""
    old = blocks.index(block)
    if index > old:
        index -= 1      # everything below shifts up once the block is taken out
    index = max(0, min(index, len(blocks) - 1))
    if index == old:
        return False
    blocks.insert(index, blocks.pop(old))
    return True


def apply_brand(design: dict, kit: dict) -> None:
    """Recolour a design from the brand kit: every brand colour, the font and empty logos."""
    page = design["page"]
    for field in PAGE_FIELDS:
        if field.brand:
            page[field.key] = kit[field.brand]
    page["font"] = kit["font"]
    for block in design["blocks"]:
        for field in fields_for(block["type"]):
            if field.brand in ("primary", "text"):
                block[field.key] = kit[field.brand]
        if block["type"] == "logo" and not block.get("image") and kit.get("logo"):
            block["image"] = add_asset(design, kit["logo"])


LINKS_EXAMPLE = "{site} | www.yourcompany.com\n{contact} | www.yourcompany.com/contact"


def example_links() -> str:
    """The links row a new block starts with, in the user's language."""
    return LINKS_EXAMPLE.format(site=t("[Our website]"), contact=t("[Contact us]"))


def blank_design() -> dict:
    return {"version": 1, "page": page_defaults(), "blocks": [], "assets": {}}


# --- starting designs -----------------------------------------------------------
# Picked from a gallery when the user makes a new design. Nothing here is ever
# created on its own: a design only exists once someone chooses one.
STARTERS = (
    ("blank", "Blank", "Only your message. Add blocks from the left."),
    ("letter", "Simple letter", "Your logo, your message and a footer. Closest to a normal email."),
    ("announcement", "Announcement", "A coloured banner, your message and a button."),
    ("welcome", "Welcome card", "A soft coloured background with a centred card, like a "
                                "welcome email."),
    ("newsletter", "Newsletter", "Logo, menu links, a picture, two columns, a quote and "
                                 "social icons."),
    ("spotlight", "Product spotlight", "A picture with words beside it and a highlighted "
                                       "offer card."),
    ("event", "Event invitation", "A big picture, the details and a button to sign up."),
    ("action", "Bold action", "A strong heading and a box with one clear button."),
)


def starter(key: str, kit: dict | None = None) -> dict:
    """A new design from one of the STARTERS, in the user's language and brand colours."""
    kit = kit or brand_kit()
    design = blank_design()
    page = design["page"]

    def add(kind: str, **settings) -> dict:
        block = new_block(kind, kit, design)
        block.update(settings)
        design["blocks"].append(block)
        return block

    footer = {"text": t("[Your company name]") + "\n" + t("[Street, city, country]")}
    if key == "letter":
        add("logo", align="left", pad_top=24)
        add("message")
        add("divider", pad_top=16)
        add("footer", align="left", **footer)
    elif key == "announcement":
        add("banner", pad_top=36, pad_bottom=36, title=t("[Your big headline]"),
            subtitle=t("[One line that says more]"))
        add("message", pad_top=24)
        add("button", label=t("[Find out more]"), pad_top=12, pad_bottom=24)
        add("footer", **footer)
    elif key == "welcome":
        page.update(gradient="diagonal", bg2="#e9e2f5", radius=20, outer_pad=40,
                    card_bg="#ffffff", shadow=True)
        add("logo", pad_top=32)
        add("heading", text=t("[Welcome aboard]"), align="center", size=30)
        add("image", width=70, radius=12)
        add("message", align="center")
        add("button", label=t("[Get started]"), radius=24, size="large", pad_bottom=24)
        add("footer", **footer)
    elif key == "newsletter":
        page.update(width=640)
        add("links", items=example_links(), pad_top=16)
        add("logo", align="left", pad_top=0)
        add("heading", text=t("[This month's news]"), size=28)
        add("image", radius=10)
        add("message")
        add("columns", left_title=t("[First title]"), right_title=t("[Second title]"),
            left_text=t("[A sentence or two about it]"),
            right_text=t("[A sentence or two about it]"))
        add("quote", text=t("[What a happy customer said about you]"),
            author=t("[Their name, their company]"))
        add("divider")
        add("social", website="www.yourcompany.com")
        add("footer", **footer)
    elif key == "spotlight":
        add("logo", pad_top=24)
        add("heading", text=t("[Meet our newest product]"), align="center")
        add("columns", ratio="33", left_title="", left_text="",
            right_title=t("[Product name]"), right_text=t("[What it does and who it is for]"),
            right_button=t("[See it]"))
        add("message")
        add("card", title=t("[A special offer for {{Company}}]"),
            text=t("[A few words about it]"), button=t("[Claim it]"))
        add("social", website="www.yourcompany.com")
        add("footer", **footer)
    elif key == "event":
        page.update(radius=12)
        add("image", pad_top=0, pad_side=0, pad_bottom=0)
        add("heading", text=t("[You are invited]"), align="center", size=32, pad_top=24)
        add("text", text=t("[Date and time]") + "\n" + t("[Place]"), align="center", size=16)
        add("message", align="center")
        add("button", label=t("[Save my place]"), size="large", pad_bottom=24)
        add("footer", **footer)
    elif key == "action":
        page.update(card_bg="#eceef1", radius=4, gradient="none")
        add("logo", width=80, pad_top=32)
        add("heading", text=t("[One clear message]"), align="center", size=28,
            weight="normal")
        add("card", title=t("[The thing to do]"), text=t("[Why it matters, in one line]"),
            button=t("[Do it now]"), align="center", card_bg="#ffffff", border="",
            radius=4)
        add("message", align="center", size=13, color="#555555")
        add("footer", **footer)
    else:
        add("message", pad_top=24, pad_bottom=24)

    if not any(b["type"] == "message" for b in design["blocks"]):
        add("message")
    return design


# --- pictures -------------------------------------------------------------------
def prepare_image(path: str | Path) -> dict:
    """Read a picture and shrink it so it travels well by email.

    Phone photos are often 4000 pixels wide and several megabytes. Nobody's email
    is wider than about 800 pixels, so pictures are cut down to 1200 (sharp on a
    high-resolution screen) and recompressed. Animated GIFs are kept as they are
    when they are small enough, because shrinking one would stop it moving.
    """
    from PIL import Image, ImageOps

    data = Path(path).read_bytes()
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError(t("That picture is over 25 MB. Choose a smaller one."))
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as error:  # noqa: BLE001
        raise ValueError(t("That file is not a picture the app can read.")) from error

    name = Path(path).name
    if image.format == "GIF" and getattr(image, "is_animated", False) \
            and len(data) <= 2 * 1024 * 1024:
        return _asset(name, "image/gif", data, image.width, image.height)

    image = ImageOps.exif_transpose(image)
    if image.width > MAX_IMAGE_WIDTH:
        height = round(image.height * MAX_IMAGE_WIDTH / image.width)
        image = image.resize((MAX_IMAGE_WIDTH, max(1, height)), Image.LANCZOS)

    transparent = image.mode in ("RGBA", "LA") or \
        (image.mode == "P" and "transparency" in image.info)
    out = io.BytesIO()
    if transparent:
        image.convert("RGBA").save(out, "PNG", optimize=True)
        mime = "image/png"
    else:
        image.convert("RGB").save(out, "JPEG", quality=85, optimize=True, progressive=True)
        mime = "image/jpeg"
    return _asset(name, mime, out.getvalue(), image.width, image.height)


def _asset(name: str, mime: str, data: bytes, width: int, height: int) -> dict:
    return {"name": name, "mime": mime, "w": int(width), "h": int(height),
            "data": base64.b64encode(data).decode("ascii")}


def _valid_asset(asset: Any) -> bool:
    return isinstance(asset, dict) and isinstance(asset.get("data"), str) \
        and asset.get("mime") in ("image/png", "image/jpeg", "image/gif")


def add_asset(design: dict, asset: dict) -> str:
    """Store a picture in the design and return the value an image setting holds."""
    for key, existing in design["assets"].items():
        if existing.get("data") == asset.get("data"):
            return "asset:" + key
    key = _new_id()
    design["assets"][key] = asset
    return "asset:" + key


def asset_bytes(design: dict, ref: str) -> tuple[bytes, str] | None:
    """The picture behind an image setting, or None for a web link or nothing."""
    if not isinstance(ref, str) or not ref.startswith("asset:"):
        return None
    asset = design.get("assets", {}).get(ref[6:])
    if not _valid_asset(asset):
        return None
    return base64.b64decode(asset["data"]), asset["mime"]


def used_assets(design: dict) -> set[str]:
    refs = set()
    for block in design["blocks"]:
        for field in fields_for(block["type"]):
            value = block.get(field.key)
            if field.kind == "image" and isinstance(value, str) and value.startswith("asset:"):
                refs.add(value[6:])
    return refs


def pictures_size(design: dict) -> int:
    """Bytes of pictures every email carries."""
    total = 0
    for key in used_assets(design):
        asset = design["assets"].get(key)
        if _valid_asset(asset):
            total += len(asset["data"]) * 3 // 4
    return total


def _font(size: int, bold: bool = True):
    from PIL import ImageFont

    for name in (("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else
                 ("arial.ttf", "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:          # Pillow before 10.1 has one fixed size
        return ImageFont.load_default()


def social_icon(network: str, colour: str, shape: str, size: int) -> bytes:
    """A social icon drawn on the spot: a coloured circle or square with letters.

    Drawn rather than shipped as brand artwork, so it can take any colour, and
    at three times the size it is shown so it stays crisp on a sharp screen.
    """
    from PIL import Image, ImageDraw

    letters = NETWORKS.get(network, ("", "#555555", "?"))[2]
    scale = 3
    side = max(16, size) * scale
    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if shape == "square":
        draw.rounded_rectangle((0, 0, side - 1, side - 1), radius=side // 5, fill=colour)
    else:
        draw.ellipse((0, 0, side - 1, side - 1), fill=colour)
    font = _font(int(side * (0.46 if len(letters) < 3 else 0.32)))
    draw.text((side / 2, side / 2), letters, fill="#ffffff", font=font, anchor="mm")
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def video_thumbnail(data: bytes, colour: str) -> bytes:
    """The thumbnail with a play button painted on, since email cannot overlay one."""
    from PIL import Image, ImageDraw

    image = Image.open(io.BytesIO(data)).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    radius = max(14, min(image.size) // 9)
    cx, cy = image.width / 2, image.height / 2
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=colour)
    side = radius * 0.9
    draw.polygon([(cx - side * 0.35, cy - side * 0.5), (cx - side * 0.35, cy + side * 0.5),
                  (cx + side * 0.55, cy)], fill=(255, 255, 255, 255))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()


# --- the email ------------------------------------------------------------------
def normalize_url(url: str) -> str:
    """People type www.example.com; an email link needs https:// in front."""
    url = (url or "").strip()
    if not url or url.startswith(("http://", "https://", "mailto:", "tel:", "{{")):
        return url
    if "@" in url and "/" not in url and " " not in url:
        return "mailto:" + url
    return "https://" + url


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _colour(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and HEX.match(value) else fallback


class _Renderer:
    """Turns a design into email HTML. ``images`` collects every inline picture used."""

    def __init__(self, design: dict, context: Mapping[str, str] | None,
                 rng: random.Random | None, embed: str):
        self.design = design
        self.page = {**page_defaults(), **design.get("page", {})}
        self.context = context
        self.rng = rng
        self.embed = embed
        self.images: dict[str, tuple[bytes, str]] = {}
        self.font = FONTS.get(self.page["font"], FONTS["Arial"])
        self.width = int(self.page["width"])

    # -- helpers --
    def words(self, text: Any) -> str:
        """Merge tags and {a|b} mixing, as in the message itself."""
        text = str(text or "")
        if self.context is None:
            return text
        return merge.render(text, self.context, html=True, rng=self.rng)

    def para(self, text: Any) -> str:
        return composer.text_to_html(self.words(text))

    def url(self, value: Any) -> str:
        value = str(value or "")
        if self.context is not None:
            value = merge.render(value, self.context, html=False, rng=self.rng)
        return _esc(normalize_url(value))

    def src(self, key: str, data: bytes, mime: str) -> str:
        self.images[key] = (data, mime)
        if self.embed == "data":
            return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
        return f"cid:{key}@homingpigeon"

    def picture(self, ref: Any) -> str:
        """The src for an image setting: an inline picture, a web link or nothing."""
        found = asset_bytes(self.design, ref)
        if found:
            return self.src(str(ref)[6:], *found)
        if isinstance(ref, str) and ref.startswith(("http://", "https://")):
            return _esc(ref)
        return ""

    def img(self, src: str, width: int, align: str = "center", radius: int = 0,
            alt: str = "", link: str = "") -> str:
        margin = {"center": "margin:0 auto;", "right": "margin:0 0 0 auto;"}.get(align, "")
        tag = (f'<img src="{src}" width="{width}" alt="{_esc(self.words(alt))}" '
               f'style="display:block;width:100%;max-width:{width}px;height:auto;border:0;'
               f'outline:none;text-decoration:none;border-radius:{int(radius)}px;{margin}">')
        href = self.url(link)
        return f'<a href="{href}" target="_blank">{tag}</a>' if href else tag

    def button(self, label: str, link: str, colour: str, text_colour: str = "#ffffff",
               radius: int = 6, size: str = "medium", align: str = "center",
               full: bool = False, border: str = "") -> str:
        if not str(label).strip():
            return ""
        pad = {"small": (8, 16, 13), "large": (16, 36, 17)}.get(size, (12, 26, 15))
        edge = f"border:1px solid {border};" if _colour(border) else ""
        table_align = "" if full else f' align="{align if align != "left" else "left"}"'
        width = ' width="100%"' if full else ""
        block = "display:block;" if full else "display:inline-block;"
        return (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"'
            f'{table_align}{width} style="margin:{"0 auto" if align == "center" else "0"};">'
            f'<tr><td align="center" bgcolor="{colour}" style="border-radius:{int(radius)}px;'
            f'background-color:{colour};">'
            f'<a href="{self.url(link) or "#"}" target="_blank" style="{block}padding:{pad[0]}px '
            f'{pad[1]}px;font-family:{self.font};font-size:{pad[2]}px;font-weight:bold;'
            f'line-height:1.2;color:{text_colour};text-decoration:none;'
            f'border-radius:{int(radius)}px;{edge}">{self.words(label)}</a>'
            f'</td></tr></table>')

    def inner_width(self, block: dict) -> int:
        return max(80, self.width - 2 * int(block.get("pad_side", 0) or 0))

    def row(self, block: dict, inner: str, align: str | None = None) -> str:
        align = align or block.get("align", "left")
        bg = _colour(block.get("bg"))
        style = (f"padding:{int(block.get('pad_top', 0))}px {int(block.get('pad_side', 0))}px "
                 f"{int(block.get('pad_bottom', 0))}px;text-align:{align};"
                 + (f"background-color:{bg};" if bg else ""))
        bg_attr = f' bgcolor="{bg}"' if bg else ""
        return f'<tr><td align="{align}"{bg_attr} style="{style}">{inner}</td></tr>'

    def text_style(self, size: int, colour: str, align: str = "left", italic: bool = False,
                   weight: str = "normal", font: str = "") -> str:
        family = FONTS.get(font, self.font)
        return (f"margin:0;font-family:{family};font-size:{int(size)}px;color:{colour};"
                f"line-height:{self.page['line']};text-align:{align};font-weight:{weight};"
                + ("font-style:italic;" if italic else ""))

    # -- blocks --
    def heading(self, b: dict) -> str:
        style = self.text_style(b["size"], b["color"], b["align"], weight=b["weight"],
                                font=b.get("font", ""))
        return self.row(b, f'<h2 style="{style}line-height:1.25;">{self.words(b["text"])}</h2>')

    def message(self, b: dict, parts: dict) -> str:
        style = self.text_style(b["size"], b["color"], b["align"])
        direction = ' dir="rtl"' if parts.get("rtl") else ""
        if parts.get("rtl"):
            style = style.replace(f"text-align:{b['align']}", "text-align:right")
        body = parts.get("message", "")
        if parts.get("brochure"):
            body += parts["brochure"]
        if b.get("signature", True) and parts.get("signature"):
            body += f'<div style="margin-top:16px;">{parts["signature"]}</div>'
        return self.row(b, f'<div{direction} style="{style}">{body}</div>')

    def text(self, b: dict) -> str:
        style = self.text_style(b["size"], b["color"], b["align"], italic=b.get("italic"))
        return self.row(b, f'<div style="{style}">{self.para(b["text"])}</div>')

    def quote(self, b: dict) -> str:
        style = self.text_style(b["size"], b["color"], "left", italic=b.get("italic"))
        author = ""
        if str(b.get("author", "")).strip():
            author = (f'<p style="{self.text_style(13, "#777777")}margin-top:6px;">'
                      f'{self.words(b["author"])}</p>')
        return self.row(b, (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'width="100%"><tr><td style="border-left:4px solid {b["bar"]};'
            f'padding:4px 0 4px 16px;"><div style="{style}">{self.para(b["text"])}</div>'
            f'{author}</td></tr></table>'), "left")

    def links(self, b: dict) -> str:
        items = []
        decoration = "underline" if b.get("underline", True) else "none"
        for line in str(b.get("items", "")).splitlines():
            if not line.strip():
                continue
            label, _bar, address = line.partition("|")
            address = address.strip() or label.strip()
            items.append(f'<a href="{self.url(address)}" target="_blank" style="color:{b["color"]};'
                         f'text-decoration:{decoration};">{self.words(label.strip())}</a>')
        style = self.text_style(b["size"], b["color"], b["align"])
        return self.row(b, f'<p style="{style}">' + "&nbsp;&nbsp;&nbsp;".join(items) + "</p>")

    def logo(self, b: dict) -> str:
        src = self.picture(b.get("image"))
        if not src:
            return ""
        return self.row(b, self.img(src, int(b["width"]), b["align"], 0, b.get("alt", ""),
                                    b.get("link", "")))

    def banner(self, b: dict) -> str:
        out = ""
        src = self.picture(b.get("image"))
        if src:
            out += f'<tr><td style="padding:0;">{self.img(src, self.width)}</td></tr>'
        title, subtitle = str(b.get("title", "")).strip(), str(b.get("subtitle", "")).strip()
        if title or subtitle:
            colour, second = b["color"], _colour(b.get("color2"))
            fade = f"background-image:linear-gradient(135deg,{colour},{second});" if second else ""
            heading = (f'<h1 style="{self.text_style(b["title_size"], b["text_color"], b["align"], weight="bold")}'
                       f'line-height:1.2;">{self.words(title)}</h1>') if title else ""
            line = (f'<p style="{self.text_style(16, b["text_color"], b["align"])}margin-top:8px;">'
                    f'{self.words(subtitle)}</p>') if subtitle else ""
            band = dict(b, bg=colour)
            row = self.row(band, heading + line)
            out += row.replace("background-color:", fade + "background-color:", 1) if fade else row
        return out

    def image(self, b: dict) -> str:
        src = self.picture(b.get("image"))
        if not src:
            return ""
        width = round(self.inner_width(b) * int(b["width"]) / 100)
        caption = ""
        if str(b.get("caption", "")).strip():
            caption = (f'<p style="{self.text_style(13, "#777777", b["align"])}margin-top:8px;">'
                       f'{self.words(b["caption"])}</p>')
        return self.row(b, self.img(src, width, b["align"], b["radius"], b.get("alt", ""),
                                    b.get("link", "")) + caption)

    def video(self, b: dict) -> str:
        found = asset_bytes(self.design, b.get("image"))
        if not found:
            return ""
        key = f"play{str(b['image'])[6:]}{b['play'].lstrip('#')}"
        src = self.src(key, video_thumbnail(found[0], b["play"]), "image/jpeg")
        width = round(self.inner_width(b) * int(b["width"]) / 100)
        return self.row(b, self.img(src, width, b["align"], b["radius"], b.get("alt", ""),
                                    b.get("url", "")))

    def button_block(self, b: dict) -> str:
        inner = self.button(b["label"], b["url"], b["color"], b["text_color"], b["radius"],
                            b["size"], b["align"], b.get("full"), b.get("border", ""))
        return self.row(b, inner) if inner else ""

    def social(self, b: dict) -> str:
        items = []
        size = int(b["size"])
        for network, (label, brand, _letters) in NETWORKS.items():
            link = str(b.get(network, "")).strip()
            if not link:
                continue
            if b["style"] == "text":
                items.append(f'<a href="{self.url(link)}" target="_blank" style="color:'
                             f'{b["color"]};text-decoration:none;font-family:{self.font};'
                             f'font-size:14px;">{_esc(t(label))}</a>')
                continue
            colour = brand if b["colours"] == "brand" else b["color"]
            key = f"social{network}{b['style']}{colour.lstrip('#')}{size}"
            src = self.src(key, social_icon(network, colour, b["style"], size), "image/png")
            items.append(f'<a href="{self.url(link)}" target="_blank" style="text-decoration:none;'
                         f'display:inline-block;margin:0 4px;"><img src="{src}" width="{size}" '
                         f'height="{size}" alt="{_esc(t(label))}" style="border:0;display:inline-block;">'
                         f'</a>')
        if not items:
            return ""
        joiner = "&nbsp;&nbsp;&middot;&nbsp;&nbsp;" if b["style"] == "text" else ""
        return self.row(b, joiner.join(items))

    def column(self, b: dict, side: str, width: int) -> str:
        out = ""
        src = self.picture(b.get(f"{side}_image"))
        if src:
            out += self.img(src, width, "center", 6)
        title = str(b.get(f"{side}_title", "")).strip()
        if title:
            style = self.text_style(18, b["title_color"], b["align"], weight="bold")
            out += f'<h3 style="{style}margin-top:{10 if src else 0}px;">{self.words(title)}</h3>'
        text = str(b.get(f"{side}_text", "")).strip()
        if text:
            out += (f'<div style="{self.text_style(14, b["color"], b["align"])}margin-top:6px;">'
                    f'{self.para(text)}</div>')
        button = self.button(b.get(f"{side}_button", ""), b.get(f"{side}_url", ""),
                             b["button_color"], size="small", align=b["align"])
        if button:
            out += f'<div style="margin-top:12px;">{button}</div>'
        return out

    def columns(self, b: dict) -> str:
        total = self.inner_width(b)
        gap = int(b["gap"])
        share = {"33": 0.34, "67": 0.66}.get(b["ratio"], 0.5)
        left = round((total - gap) * share)
        right = total - gap - left
        half = gap // 2
        return self.row(b, (
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">'
            f'<tr><td class="hp-col" width="{left}" valign="top" style="width:{left}px;'
            f'padding-right:{half}px;">{self.column(b, "left", left)}</td>'
            f'<td class="hp-col" width="{right}" valign="top" style="width:{right}px;'
            f'padding-left:{gap - half}px;">{self.column(b, "right", right)}</td></tr></table>'))

    def card(self, b: dict) -> str:
        inner_pad = int(b["inner"])
        inner_width = self.inner_width(b) - 2 * inner_pad
        out = ""
        src = self.picture(b.get("image"))
        if src:
            out += f'<div style="margin-bottom:12px;">{self.img(src, inner_width, "center", 6)}</div>'
        if str(b.get("title", "")).strip():
            out += (f'<h3 style="{self.text_style(18, b["title_color"], b["align"], weight="bold")}">'
                    f'{self.words(b["title"])}</h3>')
        if str(b.get("text", "")).strip():
            out += (f'<div style="{self.text_style(14, b["color"], b["align"])}margin-top:6px;">'
                    f'{self.para(b["text"])}</div>')
        button = self.button(b.get("button", ""), b.get("url", ""), b["button_color"],
                             align=b["align"], radius=min(int(b["radius"]), 24))
        if button:
            out += f'<div style="margin-top:16px;">{button}</div>'
        border = f"border:1px solid {b['border']};" if _colour(b.get("border")) else ""
        return self.row(b, (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
            f'bgcolor="{b["card_bg"]}" style="background-color:{b["card_bg"]};'
            f'border-radius:{int(b["radius"])}px;{border}"><tr><td style="padding:{inner_pad}px;'
            f'text-align:{b["align"]};">{out}</td></tr></table>'))

    def divider(self, b: dict) -> str:
        return self.row(b, (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'width="{int(b["width"])}%" align="center" style="margin:0 auto;"><tr><td style="'
            f'border-top:{int(b["thickness"])}px {b["style"]} {b["color"]};font-size:0;'
            f'line-height:0;height:1px;">&nbsp;</td></tr></table>'), "center")

    def spacer(self, b: dict) -> str:
        bg = _colour(b.get("bg"))
        colour = f' bgcolor="{bg}" style="background-color:{bg};' if bg else ' style="'
        return (f'<tr><td height="{int(b["height"])}"{colour}font-size:0;line-height:0;'
                f'height:{int(b["height"])}px;">&nbsp;</td></tr>')

    def footer(self, b: dict, parts: dict) -> str:
        style = self.text_style(b["size"], b["color"], b["align"])
        out = f'<div style="{style}">{self.para(b["text"])}</div>' if str(b["text"]).strip() else ""
        if parts.get("unsubscribe") and not parts.get("unsubscribe_used"):
            parts["unsubscribe_used"] = True
            out += f'<div style="{style}">{parts["unsubscribe"]}</div>'
        return self.row(b, out) if out else ""

    def html_block(self, b: dict) -> str:
        return self.row(b, self.words(b.get("code", "")))

    # -- the whole email --
    def email(self, parts: dict) -> str:
        page = self.page
        rows = []
        handlers = {"button": self.button_block, "html": self.html_block}
        for block in self.design["blocks"]:
            kind = block["type"]
            if kind == "message":
                rows.append(self.message(block, parts))
            elif kind == "footer":
                rows.append(self.footer(block, parts))
            else:
                rows.append((handlers.get(kind) or getattr(self, kind))(block))
        if parts.get("unsubscribe") and not parts.get("unsubscribe_used"):
            end = {"type": "footer", "pad_top": 12, "pad_bottom": 20, "pad_side": 32}
            style = self.text_style(11, "#777777", "left")
            rows.append(self.row(end, f'<div style="{style}">{parts["unsubscribe"]}</div>'))

        bg = _colour(page["bg"], "#f4f5f7")
        fade = ""
        if page["gradient"] != "none":
            angle = {"down": "180deg", "across": "90deg"}.get(page["gradient"], "135deg")
            fade = f"background-image:linear-gradient({angle},{bg},{_colour(page['bg2'], bg)});"
        card_bg = _colour(page["card_bg"], "#ffffff")
        border = f"border:1px solid {page['border']};" if _colour(page.get("border")) else ""
        shadow = "box-shadow:0 6px 24px rgba(0,0,0,0.10);" if page.get("shadow") else ""
        align = "left" if page["position"] == "left" else "center"
        preheader = ""
        text = str(page.get("preheader", "")).strip()
        if text:
            preheader = (f'<div style="display:none;max-height:0;overflow:hidden;font-size:1px;'
                         f'line-height:1px;color:{bg};opacity:0;">{self.words(text)}</div>')
        link = _colour(page["link"], "#2f7fd8")
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="x-apple-disable-message-reformatting">'
            f'<style>a{{color:{link};}}img{{-ms-interpolation-mode:bicubic;}}'
            f'@media (max-width:{self.width + 20}px){{.hp-wrap{{width:100%!important;}}'
            '.hp-col{display:block!important;width:100%!important;padding:0 0 16px 0!important;}}'
            '</style></head>'
            f'<body style="margin:0;padding:0;background-color:{bg};">{preheader}'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'bgcolor="{bg}" style="background-color:{bg};{fade}"><tr>'
            f'<td align="{align}" style="padding:{int(page["outer_pad"])}px 10px;">'
            f'<table role="presentation" class="hp-wrap" width="{self.width}" cellpadding="0" '
            f'cellspacing="0" border="0" align="{align}" bgcolor="{card_bg}" style="width:'
            f'{self.width}px;max-width:100%;background-color:{card_bg};border-radius:'
            f'{int(page["radius"])}px;{border}{shadow}border-collapse:separate;overflow:hidden;'
            f'font-family:{self.font};font-size:{int(page["size"])}px;color:{page["text"]};'
            f'line-height:{page["line"]};">'
            + "".join(r for r in rows if r)
            + '</table></td></tr></table></body></html>')


def render(design: dict, *, message_html: str = "", signature_html: str = "",
           brochure_html: str = "", unsubscribe_html: str = "",
           context: Mapping[str, str] | None = None, rng: random.Random | None = None,
           embed: str = "cid", rtl: bool = False) -> tuple[str, dict[str, tuple[bytes, str]]]:
    """The finished email HTML and the inline pictures it uses, keyed by content id.

    ``embed`` is "cid" for sending (pictures go along as parts of the email) or
    "data" for a preview in a browser, which cannot see those parts.
    """
    renderer = _Renderer(design, context, rng, embed)
    parts = {"message": message_html, "signature": signature_html,
             "brochure": brochure_html, "unsubscribe": unsubscribe_html, "rtl": rtl}
    return renderer.email(parts), renderer.images


# --- checking a design that came from a file or the database ----------------------
def _clean_value(field: Field, value: Any) -> Any:
    if field.kind == "number":
        try:
            return max(field.low, min(field.high, int(value)))
        except (TypeError, ValueError):
            return field.default
    if field.kind == "bool":
        return bool(value)
    if field.kind == "color":
        if value in ("", None) and (field.optional or field.default == ""):
            return ""
        return value if isinstance(value, str) and HEX.match(value) else field.default
    if field.kind == "choice":
        return value if value in {v for v, _label in field.options} else field.default
    if field.kind == "font":
        return value if value in FONTS or (value == "" and field.default == "") \
            else field.default
    if field.kind == "image":
        return value if isinstance(value, str) and (
            value.startswith("asset:") or value.startswith(("http://", "https://"))) else ""
    return value if isinstance(value, str) else field.default


def validate(raw: Any) -> dict:
    """A clean design from untrusted data, keeping whatever makes sense.

    Every value is checked against its field, unknown blocks and settings are
    dropped, and a design without a "Your message" block gets one, because
    without it nobody's message would be sent.
    """
    if not isinstance(raw, dict):
        raise ValueError(t("That is not a HomingPigeon design."))
    design = blank_design()
    page = raw.get("page") if isinstance(raw.get("page"), dict) else {}
    for field in PAGE_FIELDS:
        design["page"][field.key] = _clean_value(field, page.get(field.key, field.default))
    assets = raw.get("assets") if isinstance(raw.get("assets"), dict) else {}
    design["assets"] = {str(k): v for k, v in assets.items() if _valid_asset(v)}

    seen = set()
    for block in raw.get("blocks") or []:
        if not isinstance(block, dict) or block.get("type") not in BLOCKS:
            continue
        clean = {"type": block["type"]}
        block_id = str(block.get("id") or _new_id())
        if block_id in seen:
            block_id = _new_id()
        seen.add(block_id)
        clean["id"] = block_id
        for field in fields_for(block["type"]):
            clean[field.key] = _clean_value(field, block.get(field.key, field.default))
        if block["type"] == "message" and any(b["type"] == "message"
                                              for b in design["blocks"]):
            continue
        design["blocks"].append(clean)
    if not any(b["type"] == "message" for b in design["blocks"]):
        design["blocks"].append(new_block("message"))
    return design


def export_text(design: dict, name: str) -> str:
    return json.dumps({"homingpigeon_design": 1, "name": name, "design": design})


def import_text(text: str) -> tuple[str, dict]:
    """(name, design) from an exported design file."""
    if len(text) > MAX_DESIGN_FILE:
        raise ValueError(t("That file is too big to be a design."))
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ValueError(t("That is not a HomingPigeon design.")) from error
    if not isinstance(data, dict) or "homingpigeon_design" not in data:
        raise ValueError(t("That is not a HomingPigeon design."))
    name = str(data.get("name") or t("Imported design"))[:80]
    return name, validate(data.get("design"))


# --- storage --------------------------------------------------------------------
def list_designs() -> list[dict]:
    return [dict(r) for r in db.query("SELECT id, name, updated_at FROM designs ORDER BY id")]


def load(design_id: int) -> dict | None:
    row = db.query_one("SELECT data FROM designs WHERE id = ?", (int(design_id),))
    if row is None:
        return None
    try:
        return validate(json.loads(row["data"]))
    except ValueError:
        return blank_design()


def save(design: dict, name: str, design_id: int | None = None) -> int:
    """Store a design, dropping pictures nothing uses any more. Returns its id."""
    kept = copy.deepcopy(design)
    used = used_assets(kept)
    kept["assets"] = {k: v for k, v in kept["assets"].items() if k in used}
    data = json.dumps(kept)
    if design_id is None:
        return db.execute("INSERT INTO designs(name, data, created_at, updated_at) "
                          "VALUES (?, ?, ?, ?)", (name, data, db.now(), db.now()))
    db.execute("UPDATE designs SET name = ?, data = ?, updated_at = ? WHERE id = ?",
               (name, data, db.now(), int(design_id)))
    return int(design_id)


def rename(design_id: int, name: str) -> None:
    db.execute("UPDATE designs SET name = ? WHERE id = ?", (name, int(design_id)))


def delete(design_id: int) -> None:
    db.execute("DELETE FROM designs WHERE id = ?", (int(design_id),))
    if active_id() == int(design_id):
        set_active(0)


def active_id() -> int:
    try:
        return int(db.get_setting("design_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def set_active(design_id: int) -> None:
    """Send emails with this design, or 0 to send them as plain messages."""
    db.set_setting("design_id", int(design_id or 0))


def active() -> dict | None:
    """The design every email is sent with, or None for a plain email."""
    design_id = active_id()
    return load(design_id) if design_id else None
