"""Render assets/logo.svg into the PNG and ICO files the app and installer use.

    python tools/make_icons.py

Needs Pillow plus Google Chrome or Microsoft Edge (used as the SVG renderer).
Only run this after changing the logo; the results are committed to the repo.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SVG = ASSETS / "logo.svg"
RENDER_SIZE = 1024

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser",
]


def find_browser() -> str | None:
    for candidate in BROWSERS:
        if os.path.isfile(candidate) or shutil.which(candidate):
            return candidate
    return None


def render(browser: str, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "logo.html"
        page.write_text(
            "<html><body style='margin:0;background:transparent'>"
            f"<img src='{SVG.as_uri()}' width='{RENDER_SIZE}' height='{RENDER_SIZE}'>"
            "</body></html>", encoding="utf-8")
        subprocess.run([
            browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--allow-file-access-from-files", f"--user-data-dir={Path(tmp) / 'profile'}",
            "--default-background-color=00000000",
            f"--window-size={RENDER_SIZE},{RENDER_SIZE}",
            f"--screenshot={out}", page.as_uri(),
        ], check=True, capture_output=True, timeout=120)


def main() -> int:
    browser = find_browser()
    if not browser:
        print("Chrome or Edge is needed to render the SVG.")
        return 1

    big = ASSETS / "logo-1024.png"
    render(browser, big)
    image = Image.open(big).convert("RGBA")

    # Trim the empty border so the pigeon fills the icon, then centre it on a square
    left, top, right, bottom = image.getbbox()
    side = int(max(right - left, bottom - top) * 1.04)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(image.crop((left, top, right, bottom)),
                           ((side - (right - left)) // 2, (side - (bottom - top)) // 2))
    image = square

    for size in (256, 192, 160, 128, 96):
        image.resize((size, size), Image.LANCZOS).save(ASSETS / f"logo-{size}.png")
    image.save(ASSETS / "icon.ico",
               sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48),
                      (64, 64), (128, 128), (256, 256)])
    big.unlink()
    print("Wrote logo PNGs and icon.ico to", ASSETS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
