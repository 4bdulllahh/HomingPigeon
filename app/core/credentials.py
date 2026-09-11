"""Encrypted, machine-bound credential storage.

On Windows the secret blob is protected with DPAPI (CryptProtectData), so it can
only be decrypted by the same Windows user on the same machine and there is no
key file sitting next to the ciphertext. Elsewhere we fall back to Fernet with a
key derived from machine identifiers.

Passwords never reach the database, the log, an export or a .env file.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import sys
import uuid
from ctypes import wintypes
from pathlib import Path

from app import config

_CACHE: dict[str, str] | None = None


# --- Windows DPAPI ----------------------------------------------------------
class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_to_bytes(blob: _DataBlob) -> bytes:
    size = blob.cbData
    buf = ctypes.create_string_buffer(size)
    ctypes.memmove(buf, blob.pbData, size)
    return buf.raw


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def _dpapi_encrypt(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    src = _DataBlob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    out = _DataBlob()
    if not crypt32.CryptProtectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptProtectData failed")
    try:
        return _blob_to_bytes(out)
    finally:
        kernel32.LocalFree(out.pbData)


def _dpapi_decrypt(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    src = _DataBlob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    out = _DataBlob()
    if not crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptUnprotectData failed")
    try:
        return _blob_to_bytes(out)
    finally:
        kernel32.LocalFree(out.pbData)


# --- Fernet fallback --------------------------------------------------------
def _machine_key() -> bytes:
    seed = "|".join(
        [
            str(uuid.getnode()),
            os.environ.get("COMPUTERNAME", "") or os.environ.get("HOSTNAME", ""),
            os.environ.get("USERNAME", "") or os.environ.get("USER", ""),
            config.APP_NAME,
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet():
    from cryptography.fernet import Fernet

    return Fernet(_machine_key())


# --- Store ------------------------------------------------------------------
def _encrypt(payload: dict[str, str]) -> bytes:
    raw = json.dumps(payload).encode("utf-8")
    if _dpapi_available():
        try:
            return b"DPAPI:" + _dpapi_encrypt(raw)
        except OSError:
            pass  # fall through to Fernet
    return b"FERNT:" + _fernet().encrypt(raw)


def _decrypt(blob: bytes) -> dict[str, str]:
    if blob.startswith(b"DPAPI:"):
        return json.loads(_dpapi_decrypt(blob[6:]).decode("utf-8"))
    if blob.startswith(b"FERNT:"):
        return json.loads(_fernet().decrypt(blob[6:]).decode("utf-8"))
    raise ValueError("Unrecognised secret store format")


def _load_all() -> dict[str, str]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = Path(config.SECRETS_PATH)
    if not path.exists():
        _CACHE = {}
        return _CACHE
    try:
        _CACHE = _decrypt(path.read_bytes())
    except Exception:
        # Unreadable store (copied from another machine, or corrupted): start clean
        # rather than blocking the app. The user just re-enters the password.
        _CACHE = {}
    return _CACHE


def _save_all(data: dict[str, str]) -> None:
    global _CACHE
    config.ensure_dirs()
    path = Path(config.SECRETS_PATH)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(_encrypt(data))
    tmp.replace(path)
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    _CACHE = data


def save_secret(name: str, value: str) -> None:
    data = dict(_load_all())
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    _save_all(data)


def load_secret(name: str, default: str = "") -> str:
    return _load_all().get(name, default)


def delete_secret(name: str) -> None:
    save_secret(name, "")


def has_secret(name: str) -> bool:
    return bool(_load_all().get(name))


def clear_all() -> None:
    _save_all({})


def backend_name() -> str:
    return "Windows DPAPI" if _dpapi_available() else "Encrypted file (machine key)"


# Well-known secret names
SMTP_PASSWORD = "smtp_password"
IMAP_PASSWORD = "imap_password"
