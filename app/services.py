from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from statistics import mean, pstdev

from app.config import settings
from app.notifier import Notifier
from app.storage import Storage
from app.strategy import StrategyEngine
from app.torn_client import TornClient

logger = logging.getLogger(__name__)


class TornNexusService:
    def __init__(self) -> None:
        self.storage = Storage(settings.database_path)
        self.client = TornClient(settings.torn_api_key, settings.torn_api_base)
        self.notifier = Notifier(settings.discord_webhook_url)
        self.strategy = StrategyEngine(
            window=settings.strategy_window,
            volatility_weight=settings.strategy_volatility_weight,
            min_drop_percent=settings.strategy_min_drop_percent,
        )

        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._energy_full_notified = False
        self._last_alert_sent_at: dict[str, float] = {}
        self._market_refresh_lock = asyncio.Lock()
        self._dynamic_tracked_item_ids: list[int] = list(settings.tracked_item_ids)

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
            asyncio.create_task(self._poll_market_loop(), name="poll-market-loop"),
        ]
        if settings.faction_id > 0:
            self._tasks.append(asyncio.create_task(self._poll_faction_loop(), name="poll-faction-loop"))

    async def stop(self) -> None:
        self._running = False

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

    async def _poll_market_loop(self) -> None:
        while self._running:
            try:
                await self.refresh_market_now()

            except Exception as exc:
                logger.exception("Market polling failed: %s", exc)
                self.storage.add_alert(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "kind": "error",
                        "message": f"Market polling error: {exc}",
                    }
                )

            await asyncio.sleep(settings.market_poll_interval_seconds)

    async def refresh_market_now(self) -> dict[str, int]:
        async with self._market_refresh_lock:
            scan_ids = self._get_scan_item_ids()
            fetched = 0
            inserted = 0
            for item_id in scan_ids:
                price_payload = await self.client.fetch_market_price(item_id)
                if not price_payload:
                    continue
                fetched += 1
                self.storage.add_market_price(price_payload)
                inserted += 1
                await self._check_price_alert(price_payload)

            if settings.auto_discovery_enabled:
                self._refresh_dynamic_tracked_item_ids(scan_ids)

            return {
                "fetched": fetched,
                "inserted": inserted,
                "tracked": len(self.get_effective_tracked_item_ids()),
                "scanned": len(scan_ids),
            }

    def get_effective_tracked_item_ids(self) -> list[int]:
        if settings.auto_discovery_enabled and self._dynamic_tracked_item_ids:
            return list(self._dynamic_tracked_item_ids)
        return list(settings.tracked_item_ids)

    def _get_scan_item_ids(self) -> list[int]:
        if settings.auto_discovery_enabled and settings.auto_discovery_pool_ids:
            return list(settings.auto_discovery_pool_ids)
        return list(settings.tracked_item_ids)

    def _refresh_dynamic_tracked_item_ids(self, candidate_ids: list[int]) -> None:
        ranked = self._rank_candidate_items(candidate_ids)
        if ranked:
            top_n = max(1, settings.auto_discovery_top_n)
            self._dynamic_tracked_item_ids = [row["item_id"] for row in ranked[:top_n]]
            return

        self._dynamic_tracked_item_ids = list(settings.tracked_item_ids)

    def _rank_candidate_items(self, candidate_ids: list[int]) -> list[dict[str, float | int]]:
        rows: list[dict[str, float | int]] = []
        window = max(8, settings.auto_discovery_stats_window)

        for item_id in candidate_ids:
            series = self.storage.get_market_prices_for_item(item_id=item_id, limit=window)
            prices = [int(row["lowest_price"]) for row in series if int(row.get("lowest_price", 0)) > 0]
            samples = len(prices)
            if samples < max(6, min(window, 12)):
                continue

            avg_price = mean(prices)
            if avg_price <= 0:
                continue

            volatility_pct = (pstdev(prices) / avg_price) * 100 if samples >= 2 else 0.0
            spread_pct = ((max(prices) - min(prices)) / avg_price) * 100 if samples >= 2 else 0.0
            liquidity_score = min(100.0, (samples / window) * 100)
            volatility_score = min(100.0, volatility_pct * 4)
            spread_score = min(100.0, spread_pct * 2.5)

            score = liquidity_score * 0.45 + volatility_score * 0.30 + spread_score * 0.25
            rows.append(
                {
                    "item_id": item_id,
                    "score": round(score, 3),
                    "liquidity": round(liquidity_score, 3),
                    "volatility": round(volatility_score, 3),
                    "spread": round(spread_score, 3),
                }
            )

        rows.sort(key=lambda row: (float(row["score"]), float(row["liquidity"])), reverse=True)
        return rows

    async def _poll_faction_loop(self) -> None:
        while self._running:
            try:
                faction_payload = await self.client.fetch_faction_data(settings.faction_id)
                self.storage.add_faction_snapshot(faction_payload)

                chain_current = faction_payload.get("chain_current", 0)
                chain_timeout = faction_payload.get("chain_timeout", 0)
                if chain_current > 0 and chain_timeout > 0 and chain_timeout < 120:
                    await self._notify(
                        "war_room",
                        f"🚨 Chain critique: {chain_current} hits, timeout dans {chain_timeout}s.",
                    )

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

    async def _check_price_alert(self, price_payload: dict) -> None:
        history = self.storage.get_market_prices_for_item(price_payload["item_id"], limit=220)
        prices = [int(row["lowest_price"]) for row in history]
        if len(prices) < settings.strategy_window:
            return

        signal = self.strategy.signal_for_series(prices)
        if signal.get("has_signal"):
            message = (
                f"🔥 BUY SIGNAL {price_payload['item_name']} ({price_payload['item_id']}): "
                f"{signal['current_price']:,}$ vs MA {signal['moving_average']:,.0f}$ "
                f"(-{signal['drop_percent']:.1f}% / seuil {signal['dynamic_threshold']:.1f}%)"
            )
            await self._notify("price_drop", message)

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
