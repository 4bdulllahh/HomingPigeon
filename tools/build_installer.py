"""Build the Windows release: "HomingPigeon Setup.exe" and the zip that goes on GitHub Releases.

    pip install -r requirements-dev.txt
    python tools/build_installer.py

Output:
    dist/HomingPigeon Setup/                            the installer, one folder
    dist/HomingPigeon-vX.Y.Z.zip, containing:
        HomingPigeon Setup.exe                          the installer (app files packed inside)
        runtime/                                        the installer's own Python and Tk
        Install HomingPigeon (if Setup is blocked).bat  backup for Smart App Control PCs
        READ ME FIRST.txt
        files/                                          app files used by the backup installer

Setup.exe carries its own copy of the app files, and downloads Python and the
add-ons on the user's computer (see installer/setup_app.py).

The zip has to be extracted before Setup runs, because Setup.exe needs the
runtime folder next to it. That is the price of not shipping a one-file build,
which Defender's machine learning classifier reads as a dropper. Both READ ME
FIRST.txt and the README say to extract first.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "installer"
DIST = ROOT / "dist"
EXE_NAME = "HomingPigeon Setup"


def app_version() -> str:
    text = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    return re.search(r'APP_VERSION\s*=\s*"(v[\d.]+)', text).group(1)


def stage_payload() -> Path:
    """Copy exactly the files the installed app needs, without caches."""
    payload = BUILD / "payload"
    shutil.rmtree(payload, ignore_errors=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.svg")
    shutil.copytree(ROOT / "app", payload / "app", ignore=ignore)
    shutil.copytree(ROOT / "assets", payload / "assets", ignore=ignore)
    shutil.copytree(ROOT / "installer", payload / "installer",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.bat", "*.txt"))
    for name in ("run.py", "requirements.txt"):
        shutil.copy2(ROOT / name, payload / name)
    return payload


def backup_installer() -> str:
    """install-if-blocked.bat, filled in with this release's pinned Python version and hashes."""
    setup = (ROOT / "installer" / "setup_app.py").read_text(encoding="utf-8")
    values = {
        "@PYTHON_VERSION@": re.search(r'PYTHON_VERSION = "([^"]+)"', setup).group(1),
        "@SHA_AMD64@": re.search(r'"amd64": \("([0-9a-f]{64})"', setup).group(1),
        "@SHA_ARM64@": re.search(r'"arm64": \("([0-9a-f]{64})"', setup).group(1),
    }
    text = (ROOT / "installer" / "install-if-blocked.bat").read_text(encoding="utf-8")
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    if re.search(r"@[A-Z_0-9]+@", text):
        raise ValueError("unfilled placeholder in the backup installer")
    return text.replace("\r\n", "\n").replace("\n", "\r\n")  # batch files need CRLF


def version_file(version: str) -> Path:
    """Windows 'Details' tab info, so the file doesn't look anonymous."""
    numbers = [int(n) for n in version.lstrip("v").split(".")] + [0, 0, 0]
    tup = tuple(numbers[:4])
    path = BUILD / "version_info.txt"
    path.write_text(f"""
VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'HomingPigeon'),
      StringStruct('FileDescription', 'HomingPigeon Setup'),
      StringStruct('FileVersion', '{version.lstrip("v")}'),
      StringStruct('InternalName', 'HomingPigeon Setup'),
      StringStruct('OriginalFilename', 'HomingPigeon Setup.exe'),
      StringStruct('ProductName', 'HomingPigeon'),
      StringStruct('ProductVersion', '{version.lstrip("v")}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")
    return path


def main() -> int:
    if sys.platform != "win32":
        print("Build the Windows installer on Windows (or let GitHub Actions do it).")
        return 1
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is required. Run: pip install -r requirements-dev.txt")
        return 1

    version = app_version()
    BUILD.mkdir(parents=True, exist_ok=True)
    payload = stage_payload()

    command = [
        sys.executable, "-m", "PyInstaller",
        "--name", EXE_NAME,
        # A one-folder build on purpose, not one file. A one-file build is a
        # small stub followed by megabytes of compressed data, which is the
        # shape of a self-extracting dropper: Microsoft Defender's machine
        # learning model called it Trojan:Win32/Wacatac.B!ml on download, and
        # none of the readable strings that show what it really does survive
        # the compression. One folder keeps the DLLs as ordinary files and the
        # .exe small and legible. --noupx in case a build machine has UPX.
        "--onedir", "--contents-directory", "runtime", "--noupx",
        "--windowed", "--clean", "--noconfirm",
        "--icon", str(ROOT / "assets" / "icon.ico"),
        "--version-file", str(version_file(version)),
        "--add-data", f"{payload};payload",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        # Setup uses only the standard library; keep anything else out of the .exe
        "--exclude-module", "PyQt6", "--exclude-module", "pandas",
        "--exclude-module", "numpy", "--exclude-module", "PIL",
        str(ROOT / "installer" / "setup_app.py"),
    ]
    print(f"Building {EXE_NAME}.exe for HomingPigeon {version}...\n")
    if subprocess.run(command, cwd=ROOT).returncode != 0:
        print("\nBuild failed.")
        return 1

    bundle = DIST / EXE_NAME
    exe = bundle / f"{EXE_NAME}.exe"
    if not exe.exists():
        print(f"\nThe build reported success but {exe} is not there.")
        return 1
    (DIST / f"{EXE_NAME}.exe").unlink(missing_ok=True)  # leftover one-file build

    archive = DIST / f"HomingPigeon-{version}.zip"
    readme = (ROOT / "installer" / "READ ME FIRST.txt").read_text(encoding="utf-8")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        # Setup.exe goes at the top of the zip with its runtime folder beside it,
        # so what the user double-clicks is still the first thing they see.
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(bundle))
        zf.writestr("Install HomingPigeon (if Setup is blocked).bat", backup_installer())
        zf.writestr("READ ME FIRST.txt", readme.replace("{version}", version).replace("\n", "\r\n"))
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                zf.write(path, Path("files") / path.relative_to(payload))

    packed = sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file())
    print(f"\nSetup:   {bundle}"
          f"\n         {exe.name} is {exe.stat().st_size / 1_048_576:.1f} MB, "
          f"{packed / 1_048_576:.1f} MB with its runtime folder")
    print(f"Release: {archive}  ({archive.stat().st_size / 1_048_576:.1f} MB)")
    print("Upload the .zip to a GitHub Release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
