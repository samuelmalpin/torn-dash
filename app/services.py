from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.notifier import Notifier
from app.storage import Storage
from app.torn_client import TornClient

logger = logging.getLogger(__name__)


@dataclass
class AutomationRule:
    name: str
    priority: int
    cooldown_seconds: int
    allowed_hours: set[int]
    enabled: bool = True


class TornNexusService:
    def __init__(self) -> None:
        self.storage = Storage(settings.database_path)
        self.client = TornClient(settings.torn_api_key, settings.torn_api_base)
        self.notifier = Notifier(settings.discord_webhook_url)

        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._energy_full_notified = False
        self._last_alert_sent_at: dict[str, float] = {}
        self._automation_task: asyncio.Task | None = None
        self._automation_running = False
        self._automation_emergency_stop = settings.automation_emergency_stop
        self._automation_last_run_at: dict[str, float] = {}
        self._automation_window_started_at: float = datetime.now(timezone.utc).timestamp()
        self._automation_actions_in_window = 0
        self._automation_rules: list[AutomationRule] = self._build_automation_rules()

    async def start(self) -> None:
        if self._running:
            return
        if not settings.torn_api_key:
            logger.warning("TORN_API_KEY is empty: polling disabled")
            return

        self._running = True
        await self.client.start()
        await self.notifier.start()

        self._tasks = [
            asyncio.create_task(self._poll_user_loop(), name="poll-user-loop"),
        ]
        if settings.faction_id > 0:
            self._tasks.append(asyncio.create_task(self._poll_faction_loop(), name="poll-faction-loop"))
        if settings.automation_enabled and not self._automation_emergency_stop:
            await self.start_automation()

    async def stop(self) -> None:
        self._running = False
        await self.stop_automation()

        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

        await self.client.stop()
        await self.notifier.stop()

    async def _poll_user_loop(self) -> None:
        while self._running:
            try:
                await self._collect_user_snapshot()

            except Exception as exc:
                logger.exception("User polling failed: %s", exc)
                self.storage.add_alert(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "kind": "error",
                        "message": f"User polling error: {exc}",
                    }
                )

            await asyncio.sleep(settings.poll_interval_seconds)

    async def _poll_faction_loop(self) -> None:
        while self._running:
            try:
                await self._collect_faction_snapshot()

            except Exception as exc:
                logger.exception("Faction polling failed: %s", exc)
                self.storage.add_alert(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "kind": "error",
                        "message": f"Faction polling error: {exc}",
                    }
                )

            await asyncio.sleep(settings.faction_poll_interval_seconds)

    async def _collect_user_snapshot(self) -> dict[str, Any]:
        user_payload = await self.client.fetch_user_data()

        snapshot = {
            "timestamp": user_payload["timestamp"],
            "level": user_payload["level"],
            "energy_current": user_payload["energy_current"],
            "energy_max": user_payload["energy_max"],
            "nerve_current": user_payload["nerve_current"],
            "nerve_max": user_payload["nerve_max"],
            "money": user_payload["money"],
            "points": user_payload["points"],
        }
        self.storage.add_user_snapshot(snapshot)

        events = user_payload.get("events", [])
        inserted = self.storage.add_events(events)
        if inserted > 0:
            await self._notify(
                "event",
                f"{inserted} nouvel(s) événement(s) Torn détecté(s).",
            )

        await self._check_energy_alert(snapshot)
        return snapshot

    async def _collect_faction_snapshot(self) -> dict[str, Any] | None:
        if settings.faction_id <= 0:
            return None

        faction_payload = await self.client.fetch_faction_data(settings.faction_id)
        self.storage.add_faction_snapshot(faction_payload)

        chain_current = faction_payload.get("chain_current", 0)
        chain_timeout = faction_payload.get("chain_timeout", 0)
        if chain_current > 0 and chain_timeout > 0 and chain_timeout < 120:
            await self._notify(
                "war_room",
                f"🚨 Chain critique: {chain_current} hits, timeout dans {chain_timeout}s.",
            )

        return faction_payload

    async def start_automation(self) -> bool:
        if self._automation_emergency_stop:
            return False
        if self._automation_running:
            return True

        self._automation_running = True
        self._automation_task = asyncio.create_task(self._automation_loop(), name="automation-loop")
        return True

    async def stop_automation(self) -> None:
        self._automation_running = False
        if self._automation_task is not None:
            self._automation_task.cancel()
            await asyncio.gather(self._automation_task, return_exceptions=True)
            self._automation_task = None

    async def set_automation_emergency_stop(self, enabled: bool) -> None:
        self._automation_emergency_stop = bool(enabled)
        if self._automation_emergency_stop:
            await self.stop_automation()

    def get_automation_status(self) -> dict[str, Any]:
        return {
            "enabled": settings.automation_enabled,
            "running": self._automation_running,
            "dry_run": settings.automation_dry_run,
            "emergency_stop": self._automation_emergency_stop,
            "max_actions_per_hour": settings.automation_max_actions_per_hour,
            "actions_executed_current_hour": self._automation_actions_in_window,
            "tick_seconds": settings.automation_tick_seconds,
            "rules": [
                {
                    "name": rule.name,
                    "enabled": rule.enabled,
                    "priority": rule.priority,
                    "cooldown_seconds": rule.cooldown_seconds,
                    "allowed_hours": sorted(rule.allowed_hours),
                    "last_run_at": self._automation_last_run_at.get(rule.name),
                }
                for rule in self._automation_rules
            ],
        }

    def get_automation_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.storage.get_bot_action_logs(limit=limit)

    async def _automation_loop(self) -> None:
        while self._running and self._automation_running:
            try:
                await self._automation_tick()
            except Exception as exc:
                logger.exception("Automation tick failed: %s", exc)
                self.storage.add_bot_action_log(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "action_name": "automation_tick",
                        "status": "error",
                        "dry_run": int(settings.automation_dry_run),
                        "priority": 0,
                        "details": str(exc),
                    }
                )
            await asyncio.sleep(max(3, settings.automation_tick_seconds))

    async def _automation_tick(self) -> None:
        if self._automation_emergency_stop:
            return

        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()
        self._refresh_hour_window(now_ts)
        if self._automation_actions_in_window >= settings.automation_max_actions_per_hour:
            return

        overview = self.storage.get_latest_overview()
        snapshot = overview.get("snapshot") if isinstance(overview, dict) else None

        for rule in sorted(self._automation_rules, key=lambda row: row.priority, reverse=True):
            if not rule.enabled:
                continue
            if now.hour not in rule.allowed_hours:
                continue
            if not self._rule_cooldown_ready(rule, now_ts):
                continue

            can_run, reason = self._rule_conditions_met(rule.name, snapshot)
            if not can_run:
                continue

            if self._automation_actions_in_window >= settings.automation_max_actions_per_hour:
                break

            await self._execute_automation_rule(rule)
            self._automation_last_run_at[rule.name] = now_ts
            self._automation_actions_in_window += 1

    def _refresh_hour_window(self, now_ts: float) -> None:
        if now_ts - self._automation_window_started_at >= 3600:
            self._automation_window_started_at = now_ts
            self._automation_actions_in_window = 0

    def _rule_cooldown_ready(self, rule: AutomationRule, now_ts: float) -> bool:
        last_ts = self._automation_last_run_at.get(rule.name)
        if last_ts is None:
            return True
        return (now_ts - last_ts) >= max(0, rule.cooldown_seconds)

    def _rule_conditions_met(self, rule_name: str, snapshot: dict[str, Any] | None) -> tuple[bool, str]:
        if rule_name == "attack":
            if not snapshot:
                return False, "snapshot_missing"
            energy_current = int(snapshot.get("energy_current", 0))
            if energy_current < settings.automation_attack_min_energy:
                return False, "not_enough_energy"
            return True, "ready"

        if rule_name == "buy":
            if not snapshot:
                return False, "snapshot_missing"
            money = int(snapshot.get("money", 0))
            if money < settings.automation_buy_min_money:
                return False, "not_enough_money"
            return True, "ready"

        if rule_name == "refresh_faction" and settings.faction_id <= 0:
            return False, "faction_not_configured"

        return True, "ready"

    async def _execute_automation_rule(self, rule: AutomationRule) -> None:
        details = ""
        status = "ok"

        if settings.automation_dry_run:
            status = "dry_run"
            details = f"Action simulée: {rule.name}"
        else:
            if rule.name == "refresh_user":
                await self._collect_user_snapshot()
                details = "Snapshot user rafraîchi"
            elif rule.name == "refresh_faction":
                await self._collect_faction_snapshot()
                details = "Snapshot faction rafraîchi"
            elif rule.name == "attack":
                status = "skipped"
                details = "Action attack non implémentée (placeholder V1)."
            elif rule.name == "buy":
                status = "skipped"
                details = "Action buy non implémentée (placeholder V1)."
            else:
                status = "skipped"
                details = "Action inconnue"

        self.storage.add_bot_action_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action_name": rule.name,
                "status": status,
                "dry_run": int(settings.automation_dry_run),
                "priority": rule.priority,
                "details": details,
            }
        )

    def _build_automation_rules(self) -> list[AutomationRule]:
        allowed_hours = self._parse_allowed_hours(settings.automation_allowed_hours)
        return [
            AutomationRule(
                name="refresh_user",
                priority=100,
                cooldown_seconds=max(5, settings.automation_refresh_user_cooldown_seconds),
                allowed_hours=allowed_hours,
                enabled=True,
            ),
            AutomationRule(
                name="refresh_faction",
                priority=80,
                cooldown_seconds=max(10, settings.automation_refresh_faction_cooldown_seconds),
                allowed_hours=allowed_hours,
                enabled=settings.faction_id > 0,
            ),
            AutomationRule(
                name="attack",
                priority=60,
                cooldown_seconds=max(30, settings.automation_attack_cooldown_seconds),
                allowed_hours=allowed_hours,
                enabled=True,
            ),
            AutomationRule(
                name="buy",
                priority=50,
                cooldown_seconds=max(30, settings.automation_buy_cooldown_seconds),
                allowed_hours=allowed_hours,
                enabled=True,
            ),
        ]

    def _parse_allowed_hours(self, raw: str) -> set[int]:
        text = raw.strip()
        if not text:
            return set(range(24))

        selected: set[int] = set()
        for part in text.split(","):
            token = part.strip()
            if not token:
                continue
            if "-" in token:
                start_raw, end_raw = token.split("-", 1)
                if not start_raw.strip().isdigit() or not end_raw.strip().isdigit():
                    continue
                start = int(start_raw.strip())
                end = int(end_raw.strip())
                if 0 <= start <= 23 and 0 <= end <= 23:
                    if start <= end:
                        selected.update(range(start, end + 1))
                    else:
                        selected.update(range(start, 24))
                        selected.update(range(0, end + 1))
                continue
            if token.isdigit():
                hour = int(token)
                if 0 <= hour <= 23:
                    selected.add(hour)

        return selected or set(range(24))

    async def _check_energy_alert(self, snapshot: dict) -> None:
        if not settings.energy_full_alert:
            return

        is_full = snapshot["energy_max"] > 0 and snapshot["energy_current"] >= snapshot["energy_max"]
        if is_full and not self._energy_full_notified:
            await self._notify("energy", "⚡ Énergie pleine: pense à dépenser ton energy.")
            self._energy_full_notified = True
        elif not is_full:
            self._energy_full_notified = False

    async def _notify(self, kind: str, message: str) -> None:
        now_ts = datetime.now(timezone.utc).timestamp()
        dedupe_key = f"{kind}:{message}"
        last_ts = self._last_alert_sent_at.get(dedupe_key)
        if last_ts is not None and (now_ts - last_ts) < settings.alert_cooldown_seconds:
            return

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "message": message,
        }
        self.storage.add_alert(payload)
        channels = settings.alert_channel_rules.get(kind, settings.alert_channel_rules.get("default", ["discord"]))
        await self.notifier.send(channels=channels, message=message, kind=kind)
        self._last_alert_sent_at[dedupe_key] = now_ts
