from dataclasses import dataclass
from pathlib import Path
import os
import secrets
from typing import Literal

from dotenv import load_dotenv # pyright: ignore[reportMissingImports]

load_dotenv()

INSECURE_DEFAULT_AUTH_SECRET = "change-this-secret"


def _parse_users(value: str) -> dict[str, dict[str, str]]:
    users: dict[str, dict[str, str]] = {}
    if not value.strip():
        return users

    for entry in value.split(","):
        raw = entry.strip()
        if not raw:
            continue
        parts = [part.strip() for part in raw.split(":")]
        if len(parts) != 3:
            continue
        username, password, role = parts
        role_value: Literal["admin", "viewer"] = "admin" if role == "admin" else "viewer"
        users[username] = {"password": password, "role": role_value}
    return users


def _parse_channel_rules(value: str) -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    if not value.strip():
        return rules

    for group in value.split(";"):
        raw_group = group.strip()
        if not raw_group or ":" not in raw_group:
            continue
        kind, channels = raw_group.split(":", 1)
        parsed_channels = [channel.strip() for channel in channels.split("|") if channel.strip()]
        if parsed_channels:
            rules[kind.strip()] = parsed_channels
    return rules


def _is_secure_auth_secret(value: str) -> bool:
    secret = value.strip()
    if not secret or secret == INSECURE_DEFAULT_AUTH_SECRET:
        return False
    return len(secret) >= 32


def _resolve_auth_secret(configured_secret: str, database_path: str, configured_secret_file: str) -> str:
    if _is_secure_auth_secret(configured_secret):
        return configured_secret.strip()

    if configured_secret_file.strip():
        secret_file = Path(configured_secret_file.strip())
    else:
        secret_file = Path(database_path).parent / ".auth_secret"

    secret_file.parent.mkdir(parents=True, exist_ok=True)

    if secret_file.exists():
        stored_secret = secret_file.read_text(encoding="utf-8").strip()
        if _is_secure_auth_secret(stored_secret):
            return stored_secret

    generated_secret = secrets.token_urlsafe(48)
    secret_file.write_text(generated_secret, encoding="utf-8")
    return generated_secret


@dataclass
class Settings:
    torn_api_key: str = os.getenv("TORN_API_KEY", "")
    torn_api_base: str = os.getenv("TORN_API_BASE", "https://api.torn.com/v2")
    torn_min_request_interval_seconds: float = float(os.getenv("TORN_MIN_REQUEST_INTERVAL_SECONDS", "0.75"))
    torn_rate_limit_retry_count: int = int(os.getenv("TORN_RATE_LIMIT_RETRY_COUNT", "2"))
    torn_rate_limit_backoff_seconds: float = float(os.getenv("TORN_RATE_LIMIT_BACKOFF_SECONDS", "4.0"))
    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    alert_cooldown_seconds: int = int(os.getenv("ALERT_COOLDOWN_SECONDS", "600"))
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    energy_full_alert: bool = os.getenv("ENERGY_FULL_ALERT", "1") == "1"
    dashboard_history_points: int = int(os.getenv("DASHBOARD_HISTORY_POINTS", "48"))
    database_path: str = os.getenv("DATABASE_PATH", "./data/torn_nexus.db")

    dashboard_users: dict[str, dict[str, str]] = None
    auth_secret: str = os.getenv("AUTH_SECRET", INSECURE_DEFAULT_AUTH_SECRET)
    auth_secret_file: str = os.getenv("AUTH_SECRET_FILE", "")
    auth_session_hours: int = int(os.getenv("AUTH_SESSION_HOURS", "12"))

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "1") == "1"
    email_from: str = os.getenv("EMAIL_FROM", "")
    email_to: str = os.getenv("EMAIL_TO", "")

    alert_channel_rules: dict[str, list[str]] = None

    faction_id: int = int(os.getenv("FACTION_ID", "0"))
    faction_poll_interval_seconds: int = int(os.getenv("FACTION_POLL_INTERVAL_SECONDS", "90"))

    automation_enabled: bool = os.getenv("AUTOMATION_ENABLED", "0") == "1"
    automation_dry_run: bool = os.getenv("AUTOMATION_DRY_RUN", "1") == "1"
    automation_tick_seconds: int = int(os.getenv("AUTOMATION_TICK_SECONDS", "15"))
    automation_max_actions_per_hour: int = int(os.getenv("AUTOMATION_MAX_ACTIONS_PER_HOUR", "30"))
    automation_allowed_hours: str = os.getenv("AUTOMATION_ALLOWED_HOURS", "0-23")
    automation_refresh_user_cooldown_seconds: int = int(os.getenv("AUTOMATION_REFRESH_USER_COOLDOWN_SECONDS", "60"))
    automation_refresh_faction_cooldown_seconds: int = int(os.getenv("AUTOMATION_REFRESH_FACTION_COOLDOWN_SECONDS", "120"))
    automation_attack_cooldown_seconds: int = int(os.getenv("AUTOMATION_ATTACK_COOLDOWN_SECONDS", "300"))
    automation_buy_cooldown_seconds: int = int(os.getenv("AUTOMATION_BUY_COOLDOWN_SECONDS", "300"))
    automation_attack_min_energy: int = int(os.getenv("AUTOMATION_ATTACK_MIN_ENERGY", "25"))
    automation_buy_min_money: int = int(os.getenv("AUTOMATION_BUY_MIN_MONEY", "100000"))
    automation_emergency_stop: bool = os.getenv("AUTOMATION_EMERGENCY_STOP", "0") == "1"

    def __post_init__(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.auth_secret = _resolve_auth_secret(self.auth_secret, self.database_path, self.auth_secret_file)
        self.dashboard_users = _parse_users(os.getenv("DASHBOARD_USERS", "admin:admin123:admin"))
        self.alert_channel_rules = _parse_channel_rules(
            os.getenv(
                "ALERT_CHANNEL_RULES",
                "price_drop:discord|telegram;energy:discord;error:discord|email;event:discord",
            )
        )


settings = Settings()
