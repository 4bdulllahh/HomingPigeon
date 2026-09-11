"""Build a standalone Windows executable with PyInstaller.

    python tools/build_exe.py

The result lands in dist/UniformersMailer.exe and needs no Python on the target
machine. Settings and the database live in %APPDATA%/UniformersMailer, so an
updated build never overwrites the user's data.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "UniformersMailer"


def main() -> int:
    try:
        import customtkinter
    except ImportError:
        print("CustomTkinter is required. Run: pip install -r requirements.txt")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is required. Run: pip install pyinstaller")
        return 1

    ctk_path = Path(customtkinter.__file__).parent
    separator = ";" if sys.platform == "win32" else ":"

    command = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile",
        "--windowed",
        "--clean",
        "--noconfirm",
        f"--add-data={ctk_path}{separator}customtkinter",
        # Pulled in dynamically, so PyInstaller cannot see them by static analysis
        "--hidden-import=PIL._tkinter_finder",
        "--hidden-import=openpyxl.cell._writer",
        "--hidden-import=dns.rdtypes.ANY.TXT",
        "--hidden-import=dns.rdtypes.ANY.MX",
        "--hidden-import=dns.rdtypes.IN.A",
        "--collect-submodules=dns",
        # Large, unused, and they bloat the build considerably
        "--exclude-module=matplotlib",
        "--exclude-module=scipy",
        "--exclude-module=notebook",
        "--exclude-module=IPython",
        "--exclude-module=pytest",
        str(ROOT / "run.py"),
    ]

    icon = ROOT / "assets" / "icon.ico"
    if icon.exists():
        command.insert(-1, f"--icon={icon}")

    print("Building — this takes a few minutes.\n")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("\nBuild failed.")
        return result.returncode

    built = ROOT / "dist" / f"{NAME}.exe"
    if built.exists():
        size = built.stat().st_size / 1_048_576
        print(f"\nBuilt: {built}  ({size:.0f} MB)")
        print("Copy this single file to any Windows PC — no Python needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
