"""TLS settings for talking to mail servers.

The system's trusted certificates are used as normal. certifi's bundle is added
on top, because some Python installs (notably python.org's on macOS) ship with
no system certificates at all, and every secure connection would fail.
"""
from __future__ import annotations

import ssl


def secure_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    try:
        import certifi

        context.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        pass  # the system certificates alone are still used
    return context
