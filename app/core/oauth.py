"""Sign in with Google or Microsoft, for mailboxes that refuse a plain password.

The browser does the signing in; the app never sees the person's password. A
tiny web server on this computer (127.0.0.1, a free port) catches Google's or
Microsoft's answer, the code in it is swapped for a long-lived "refresh token",
and that token is stored encrypted like any password. Each time the app sends or
reads mail it trades the refresh token for a short-lived access token and signs
in with XOAUTH2, which Gmail, Outlook and Microsoft 365 all accept.

Two slots, "smtp" and "imap", so someone can send through one service (Brevo,
say) and read replies from a Gmail inbox that collects several addresses.

The app IDs come from ``app.config``: HomingPigeon has to be registered once with
each company, see docs/handover/sign-in-setup.md. Until an ID is filled in, that
company's sign-in button is not shown.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

from app import config
from app.core import credentials, tls
from app.i18n import t


class OAuthError(Exception):
    """Something the user can act on, already in plain words."""


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    auth_url: str
    token_url: str
    scope: str
    smtp_host: str
    imap_host: str

    @property
    def client_id(self) -> str:
        return getattr(config, f"{self.key.upper()}_CLIENT_ID", "")

    @property
    def client_secret(self) -> str:
        # Google gives desktop apps a "secret" that it says is not treated as one
        return getattr(config, f"{self.key.upper()}_CLIENT_SECRET", "")


PROVIDERS = {
    "google": Provider(
        "google", "Google", "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token", "https://mail.google.com/ openid email",
        "smtp.gmail.com", "imap.gmail.com"),
    "microsoft": Provider(
        "microsoft", "Microsoft",
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "https://outlook.office.com/IMAP.AccessAsUser.All "
        "https://outlook.office.com/SMTP.Send offline_access openid email",
        "smtp.office365.com", "outlook.office365.com"),
}

SIGN_IN_TIMEOUT_SECONDS = 300
_tokens: dict[str, tuple[str, float]] = {}      # slot -> (access token, expires at)
_lock = threading.Lock()


def available() -> list[Provider]:
    """The sign-in buttons to show: only companies HomingPigeon is registered with."""
    return [p for p in PROVIDERS.values() if p.client_id]


# --- the stored sign-in -------------------------------------------------------
def _secret_name(slot: str) -> str:
    return f"oauth_{slot}"


def account(slot: str) -> dict | None:
    """{"provider", "email", "refresh_token"} for "smtp" or "imap", or None."""
    raw = credentials.load_secret(_secret_name(slot))
    try:
        data = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None
    return data if data and data.get("provider") in PROVIDERS else None


def save(slot: str, data: dict) -> None:
    credentials.save_secret(_secret_name(slot), json.dumps(data))
    with _lock:
        _tokens.pop(slot, None)


def forget(slot: str) -> None:
    credentials.delete_secret(_secret_name(slot))
    with _lock:
        _tokens.pop(slot, None)


# --- talking to Google / Microsoft ----------------------------------------------
def _post(url: str, fields: dict) -> dict:
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30, context=tls.secure_context()) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
        except (ValueError, OSError):
            body = {}
        if body.get("error") == "invalid_grant":
            raise OAuthError(t("Your sign-in has expired or was withdrawn. Open My email "
                               "account and sign in again.")) from error
        detail = body.get("error_description") or body.get("error") or str(error)
        raise OAuthError(t("Sign-in was refused: {detail}", detail=detail)) from error
    except (urllib.error.URLError, OSError) as error:
        raise OAuthError(t("Could not reach the sign-in service: {error}",
                           error=error)) from error


def email_from_id_token(id_token: str) -> str:
    """The address in the identity token that came with the sign-in.

    It arrived straight from Google or Microsoft over HTTPS, so it is read, not verified.
    """
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return ""
    return str(claims.get("email") or claims.get("preferred_username") or "").lower()


class _Catcher(BaseHTTPRequestHandler):
    """Receives the browser once the person has signed in."""

    answer: dict = {}

    def do_GET(self):  # noqa: N802 - http.server naming
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" not in query and "error" not in query:
            self.send_response(404)
            self.end_headers()
            return
        type(self).answer.update({key: values[0] for key, values in query.items()})
        page = t("You can close this tab and go back to HomingPigeon.")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'>"
                         f"<h2>{page}</h2></body></html>".encode())

    def log_message(self, *args):  # the app has no console to print to
        pass


def sign_in(provider_key: str, cancelled=lambda: False, open_url=webbrowser.open) -> dict:
    """Open the browser, wait for the person to sign in and return the account to save.

    Slow (it waits for a person), so it runs on a worker thread.
    """
    provider = PROVIDERS[provider_key]
    if not provider.client_id:
        raise OAuthError(t("Sign in with {label} is not set up in this copy of HomingPigeon.",
                           label=provider.label))

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)

    catcher = type("Catcher", (_Catcher,), {"answer": {}})
    server = HTTPServer(("127.0.0.1", 0), catcher)
    server.timeout = 0.5
    host = "localhost" if provider.key == "microsoft" else "127.0.0.1"
    redirect = f"http://{host}:{server.server_port}/"
    try:
        query = {
            "client_id": provider.client_id, "redirect_uri": redirect,
            "response_type": "code", "scope": provider.scope, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
            # Google only hands out a refresh token when asked for "offline" access
            "access_type": "offline", "prompt": "consent" if provider.key == "google"
            else "select_account",
        }
        open_url(f"{provider.auth_url}?{urllib.parse.urlencode(query)}")
        deadline = time.monotonic() + SIGN_IN_TIMEOUT_SECONDS
        while not catcher.answer and time.monotonic() < deadline and not cancelled():
            server.handle_request()
    finally:
        server.server_close()

    answer = catcher.answer
    if not answer:
        raise OAuthError(t("Sign-in was not finished. Press the button to try again."))
    if answer.get("state") != state:
        raise OAuthError(t("The sign-in answer did not match. Press the button to try again."))
    if "error" in answer:
        if answer["error"] == "access_denied":
            raise OAuthError(t("Sign-in was cancelled, so nothing was changed."))
        raise OAuthError(t("Sign-in was refused: {detail}",
                           detail=answer.get("error_description") or answer["error"]))

    fields = {"client_id": provider.client_id, "code": answer.get("code", ""),
              "redirect_uri": redirect, "grant_type": "authorization_code",
              "code_verifier": verifier}
    if provider.client_secret:
        fields["client_secret"] = provider.client_secret
    tokens = _post(provider.token_url, fields)
    if not tokens.get("refresh_token"):
        raise OAuthError(t("{label} did not allow the app to stay signed in. Try again.",
                           label=provider.label))
    email = email_from_id_token(tokens.get("id_token", ""))
    if "@" not in email:
        raise OAuthError(t("{label} did not say which email address you signed in with. "
                           "Try again.", label=provider.label))
    return {"provider": provider.key, "refresh_token": tokens["refresh_token"], "email": email}


def access_token(slot: str) -> tuple[str, str]:
    """(email, access token) for the slot, refreshed when the old one is about to run out."""
    data = account(slot)
    if data is None:
        raise OAuthError(t("You are not signed in. Open My email account and sign in."))
    with _lock:
        cached = _tokens.get(slot)
        if cached and cached[1] > time.time() + 60:
            return data["email"], cached[0]

    provider = PROVIDERS[data["provider"]]
    fields = {"client_id": provider.client_id, "grant_type": "refresh_token",
              "refresh_token": data["refresh_token"]}
    if provider.client_secret:
        fields["client_secret"] = provider.client_secret
    tokens = _post(provider.token_url, fields)
    if tokens.get("refresh_token") and tokens["refresh_token"] != data["refresh_token"]:
        # Microsoft hands out a new refresh token now and then; the newest one is kept
        save(slot, {**data, "refresh_token": tokens["refresh_token"]})
    with _lock:
        _tokens[slot] = (tokens["access_token"], time.time() + int(tokens.get("expires_in", 3600)))
    return data["email"], tokens["access_token"]


def xoauth2(email: str, token: str) -> str:
    """The XOAUTH2 sign-in line that SMTP and IMAP servers expect."""
    return f"user={email}\x01auth=Bearer {token}\x01\x01"
