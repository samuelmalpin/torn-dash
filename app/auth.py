from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings


_INSECURE_DEFAULT_SECRET = "change-this-secret"


def is_auth_secret_secure() -> bool:
    secret = settings.auth_secret.strip()
    if not secret or secret == _INSECURE_DEFAULT_SECRET:
        return False
    return len(secret) >= 32


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload_b64: str) -> str:
    digest = hmac.new(settings.auth_secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return _b64_encode(digest)


def create_session_token(username: str, role: str) -> str:
    if not is_auth_secret_secure():
        raise RuntimeError("AUTH_SECRET is not secure enough")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.auth_session_hours)
    payload = {
        "username": username,
        "role": role,
        "exp": int(expires_at.timestamp()),
    }
    payload_b64 = _b64_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature_b64 = _sign(payload_b64)
    return f"{payload_b64}.{signature_b64}"


def decode_session_token(token: str) -> dict[str, Any] | None:
    if not is_auth_secret_secure():
        return None

    if not token or "." not in token:
        return None

    payload_b64, signature_b64 = token.split(".", 1)
    expected = _sign(payload_b64)
    if not hmac.compare_digest(signature_b64, expected):
        return None

    try:
        payload_raw = _b64_decode(payload_b64)
        payload = json.loads(payload_raw.decode())
    except Exception:
        return None

    exp = int(payload.get("exp", 0))
    if datetime.now(timezone.utc).timestamp() > exp:
        return None

    username = str(payload.get("username", ""))
    role = str(payload.get("role", ""))
    if not username or role not in {"admin", "viewer"}:
        return None
    return payload


def authenticate_user(username: str, password: str) -> dict[str, str] | None:
    profile = settings.dashboard_users.get(username)
    if not profile:
        return None
    if profile.get("password") != password:
        return None
    return {"username": username, "role": profile.get("role", "viewer")}
