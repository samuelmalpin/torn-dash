from dataclasses import dataclass
from pathlib import Path
import os
import secrets
from typing import Literal

from dotenv import load_dotenv # pyright: ignore[reportMissingImports]

load_dotenv()

DEFAULT_TRACKED_ITEM_IDS = (
    "372,403,1143,1084,1301,42,37,1123,1300,956,172,394,1306,1094,180,884,210,209,310,43,"
    "1201,1205,205,1303,392,1125,68,1081,1078,1083,1082,196,1079,1458,67,66,1302,1344,731,"
    "1459,1460,883,1457,1219,1080,527,365,206,366,370"
)
INSECURE_DEFAULT_AUTH_SECRET = "change-this-secret"


def _parse_int_list(value: str) -> list[int]:
    if not value.strip():
        return []
    return [int(part.strip()) for part in value.split(",") if part.strip().isdigit()]


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
    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    market_poll_interval_seconds: int = int(os.getenv("MARKET_POLL_INTERVAL_SECONDS", "120"))
    tracked_item_ids: list[int] = None
    auto_discovery_enabled: bool = os.getenv("AUTO_DISCOVERY_ENABLED", "0") == "1"
    auto_discovery_pool_ids: list[int] = None
    auto_discovery_top_n: int = int(os.getenv("AUTO_DISCOVERY_TOP_N", "12"))
    auto_discovery_stats_window: int = int(os.getenv("AUTO_DISCOVERY_STATS_WINDOW", "36"))
    price_drop_alert_percent: float = float(os.getenv("PRICE_DROP_ALERT_PERCENT", "12"))
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

    strategy_window: int = int(os.getenv("STRATEGY_WINDOW", "12"))
    strategy_volatility_weight: float = float(os.getenv("STRATEGY_VOLATILITY_WEIGHT", "1.5"))
    strategy_min_drop_percent: float = float(os.getenv("STRATEGY_MIN_DROP_PERCENT", "4.0"))

    backtest_horizon_steps: int = int(os.getenv("BACKTEST_HORIZON_STEPS", "4"))
    backtest_profit_target_percent: float = float(os.getenv("BACKTEST_PROFIT_TARGET_PERCENT", "5.0"))
    trading_budget_default: int = int(os.getenv("TRADING_BUDGET_DEFAULT", "5000000"))
    trading_max_positions: int = int(os.getenv("TRADING_MAX_POSITIONS", "4"))

    faction_id: int = int(os.getenv("FACTION_ID", "0"))
    faction_poll_interval_seconds: int = int(os.getenv("FACTION_POLL_INTERVAL_SECONDS", "90"))

    def __post_init__(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.tracked_item_ids = _parse_int_list(os.getenv("TRACKED_ITEM_IDS", DEFAULT_TRACKED_ITEM_IDS))
        self.auto_discovery_pool_ids = _parse_int_list(
            os.getenv("AUTO_DISCOVERY_POOL_IDS", DEFAULT_TRACKED_ITEM_IDS)
        )
        self.auth_secret = _resolve_auth_secret(self.auth_secret, self.database_path, self.auth_secret_file)
        self.dashboard_users = _parse_users(os.getenv("DASHBOARD_USERS", "admin:admin123:admin"))
        self.alert_channel_rules = _parse_channel_rules(
            os.getenv(
                "ALERT_CHANNEL_RULES",
                "price_drop:discord|telegram;energy:discord;error:discord|email;event:discord",
            )
        )


settings = Settings()
