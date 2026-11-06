"""
Official (institutional) e-mail verification with a one-time code sent by e-mail.

The code is sent through an SMTP account the user (or the institution's IT team) configures once —
for example a Gmail address with an *app password*, or the institution's own mail server. Only a
SHA-256 hash of the code is stored, it expires after 15 minutes and allows 5 attempts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path

CODE_MINUTES = 15
MAX_TRIES = 5
FREE_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com",
                "rediffmail.com", "icloud.com", "proton.me", "protonmail.com", "aol.com", "zoho.com", "gmx.com"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


class VerifyError(Exception):
    pass


def data_dir() -> Path:
    d = Path(os.getenv("AUTHORSHAND_DATA_DIR") or Path.home() / ".authorshand")
    d.mkdir(parents=True, exist_ok=True)
    return d


def smtp_path() -> Path:
    return data_dir() / "smtp.json"


def load_smtp() -> dict:
    env = {k: os.getenv(f"AUTHORSHAND_SMTP_{k.upper()}", "") for k in ("host", "port", "user", "password", "sender")}
    if env["host"]:
        return env
    try:
        return json.loads(smtp_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_smtp(host: str, port: int, user: str, password: str, sender: str = "") -> None:
    smtp_path().write_text(json.dumps({"host": host.strip(), "port": int(port), "user": user.strip(),
                                       "password": password, "sender": (sender or user).strip()}), encoding="utf-8")
    try:
        os.chmod(smtp_path(), 0o600)
    except Exception:
        pass


def is_institutional(email: str) -> bool:
    return bool(EMAIL_RE.match(email or "")) and email.split("@")[1].lower() not in FREE_DOMAINS


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def new_code() -> tuple[str, dict]:
    code = f"{secrets.randbelow(10**6):06d}"
    return code, {"hash": _hash(code), "expires": time.time() + CODE_MINUTES * 60, "tries": 0}


def send_code(to: str, code: str, name: str = "", cfg: dict | None = None, app: str = "Author's Hand") -> None:
    cfg = cfg or load_smtp()
    if not cfg.get("host"):
        raise VerifyError("E-mail sending is not set up yet — see Settings → Sign-in providers → E-mail for "
                          "verification codes.")
    msg = EmailMessage()
    msg["Subject"] = f"{app}: your verification code {code}"
    msg["From"] = cfg.get("sender") or cfg.get("user")
    msg["To"] = to
    msg.set_content(f"Hello {name or ''},\n\nYour {app} verification code is: {code}\n\nIt is valid for "
                    f"{CODE_MINUTES} minutes. If you did not ask for it, ignore this e-mail.\n")
    port = int(cfg.get("port") or 587)
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(cfg["host"], port, context=ctx, timeout=30) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)


def check_code(pending: dict, code: str) -> tuple[bool, str]:
    """Returns (ok, message) and increments the attempt counter in `pending`."""
    if not pending or not pending.get("hash"):
        return False, "Ask for a code first."
    if time.time() > pending.get("expires", 0):
        return False, "The code has expired — send a new one."
    if pending.get("tries", 0) >= MAX_TRIES:
        return False, "Too many attempts — send a new code."
    pending["tries"] = pending.get("tries", 0) + 1
    if secrets.compare_digest(_hash((code or "").strip()), pending["hash"]):
        return True, "Verified."
    return False, f"That code is not correct ({MAX_TRIES - pending['tries']} attempt(s) left)."
