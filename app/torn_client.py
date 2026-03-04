from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from time import monotonic
from typing import Any

import aiohttp # pyright: ignore[reportMissingImports]

from app.config import settings


logger = logging.getLogger(__name__)


class TornApiError(RuntimeError):
    def __init__(self, code: int | None, message: str, raw: Any = None) -> None:
        self.code = code
        self.message = message
        self.raw = raw
        super().__init__(f"Torn API error ({code}): {message}" if code is not None else f"Torn API error: {message}")


class TornClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v2"):
            self.base_v1_url = self.base_url[: -len("/v2")]
            self.base_v2_url = self.base_url
        elif self.base_url.endswith("/v1"):
            self.base_v1_url = self.base_url
            self.base_v2_url = f"{self.base_url[: -len('/v1')]}/v2"
        else:
            self.base_v1_url = self.base_url
            self.base_v2_url = f"{self.base_url}/v2"
        self._session: aiohttp.ClientSession | None = None
        self._diagnostics_once: set[str] = set()
        self._request_lock = asyncio.Lock()
        self._last_request_started_at = 0.0

    async def start(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25))

    async def stop(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _get(self, path: str, params: dict[str, Any], *, base_url: str | None = None) -> Any:
        if self._session is None:
            raise RuntimeError("TornClient not started")

        enriched_params = {**params, "key": self.api_key}
        effective_base = (base_url or self.base_url).rstrip("/")
        url = f"{effective_base}/{path.lstrip('/')}"

        retries = max(0, settings.torn_rate_limit_retry_count)
        for attempt in range(retries + 1):
            await self._apply_request_spacing()
            try:
                async with self._session.get(url, params=enriched_params) as response:
                    if response.status == 429:
                        raise TornApiError(5, "Too many requests (HTTP 429)")
                    response.raise_for_status()
                    payload = await response.json()
            except aiohttp.ClientResponseError as exc:
                if exc.status == 429 and attempt < retries:
                    await self._sleep_rate_limited(attempt, url)
                    continue
                raise

            if isinstance(payload, dict) and "error" in payload:
                parsed_error = self._parse_torn_error(payload.get("error"))
                if parsed_error.code == 5 and attempt < retries:
                    await self._sleep_rate_limited(attempt, url)
                    continue
                raise parsed_error

            return payload

        raise TornApiError(5, "Too many requests")

    @staticmethod
    def _parse_torn_error(error_payload: Any) -> TornApiError:
        if isinstance(error_payload, dict):
            error_code = error_payload.get("code")
            try:
                parsed_code = int(error_code) if error_code is not None else None
            except (TypeError, ValueError):
                parsed_code = None
            error_message = str(error_payload.get("error", "Unknown error"))
            return TornApiError(parsed_code, error_message, error_payload)

        return TornApiError(None, str(error_payload), error_payload)

    async def _apply_request_spacing(self) -> None:
        minimum_interval = max(0.0, settings.torn_min_request_interval_seconds)
        if minimum_interval <= 0:
            return

        async with self._request_lock:
            now = monotonic()
            elapsed = now - self._last_request_started_at
            wait = minimum_interval - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_started_at = monotonic()

    async def _sleep_rate_limited(self, attempt: int, url: str) -> None:
        base_delay = max(0.5, settings.torn_rate_limit_backoff_seconds)
        sleep_seconds = base_delay * (attempt + 1)
        logger.warning(
            "Torn API rate limit hit (attempt %s). Retrying in %.1fs for %s",
            attempt + 1,
            sleep_seconds,
            url,
        )
        await asyncio.sleep(sleep_seconds)

    async def _get_with_v2_fallback(self, path: str, params: dict[str, Any]) -> Any:
        base_is_v2 = self.base_url.rstrip("/").endswith("/v2")
        initial_base = self.base_v2_url if base_is_v2 else self.base_v1_url
        try:
            return await self._get(path, params, base_url=initial_base)
        except TornApiError as exc:
            if exc.code == 23 and not base_is_v2:
                return await self._get(path, params, base_url=self.base_v2_url)
            if exc.code == 22 and base_is_v2:
                return await self._get(path, params, base_url=self.base_v1_url)
            if exc.code in {22, 23}:
                raise
            raise

    async def _get_first_supported(self, path: str, selections_candidates: list[str]) -> dict[str, Any]:
        last_error: TornApiError | None = None
        for selection in selections_candidates:
            try:
                return await self._get_with_v2_fallback(path, {"selections": selection})
            except TornApiError as exc:
                last_error = exc
                if exc.code != 4:
                    raise
        if last_error:
            raise last_error
        raise TornApiError(None, "no supported selections")

    async def fetch_user_data(self) -> dict[str, Any]:
        base_payload = await self._get_first_supported(
            "user",
            [
                "profile,bars,events",
                "basic,bars,events",
            ],
        )

        payload: dict[str, Any] = dict(base_payload)

        money_payload = await self._get_optional_first_supported(
            "user",
            [
                "money",
                "currency",
            ],
        )
        if money_payload:
            payload.update(money_payload)

        bars = payload.get("bars", {})
        money_data = payload.get("money", {})
        currency_data = payload.get("currency", {})
        points_data = payload.get("points", {})
        profile_data = payload.get("profile", {}) if isinstance(payload.get("profile"), dict) else {}

        level_value = self._first_int(
            payload.get("level"),
            profile_data.get("level"),
            profile_data.get("player_level"),
        )

        money_value = self._first_int(
            money_data.get("money_onhand") if isinstance(money_data, dict) else None,
            money_data.get("onhand") if isinstance(money_data, dict) else None,
            currency_data.get("money_onhand") if isinstance(currency_data, dict) else None,
            currency_data.get("onhand") if isinstance(currency_data, dict) else None,
            profile_data.get("money_onhand"),
            profile_data.get("onhand"),
            payload.get("money_onhand"),
            self._find_first_int_by_keys(
                payload,
                {
                    "money_onhand",
                    "onhand",
                    "wallet",
                    "cash",
                    "money",
                },
            ),
        )

        points_value = self._first_int(
            points_data.get("points") if isinstance(points_data, dict) else points_data,
            profile_data.get("points"),
            profile_data.get("pointsbalance"),
            profile_data.get("points_balance"),
            payload.get("points"),
            self._find_first_int_by_keys(
                payload,
                {
                    "points",
                    "pointsbalance",
                    "points_balance",
                    "pointsavailable",
                    "available_points",
                },
            ),
        )

        if money_value == 0 or points_value == 0:
            payload_keys = sorted(payload.keys()) if isinstance(payload, dict) else []
            self._log_diagnostic_once(
                f"user-zero-values:{money_value}:{points_value}:{','.join(payload_keys)}",
                "User snapshot has zero values (money=%s, points=%s). payload keys=%s base=%s",
                money_value,
                points_value,
                payload_keys,
                self.base_url,
            )

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level_value,
            "energy_current": int(bars.get("energy", {}).get("current", 0)),
            "energy_max": int(bars.get("energy", {}).get("maximum", 0)),
            "nerve_current": int(bars.get("nerve", {}).get("current", 0)),
            "nerve_max": int(bars.get("nerve", {}).get("maximum", 0)),
            "money": money_value,
            "points": points_value,
            "events": self._extract_events(payload.get("events", {})),
        }

    @staticmethod
    def _first_int(*values: Any) -> int:
        for value in values:
            if isinstance(value, bool) or value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return 0

    @staticmethod
    def _find_first_int_by_keys(source: Any, keys: set[str], depth: int = 0) -> int | None:
        if depth > 4:
            return None

        lowered_keys = {key.lower() for key in keys}

        if isinstance(source, dict):
            for key, value in source.items():
                if str(key).lower() in lowered_keys:
                    try:
                        if value is None or isinstance(value, bool):
                            continue
                        return int(value)
                    except (TypeError, ValueError):
                        pass
            for value in source.values():
                nested = TornClient._find_first_int_by_keys(value, keys, depth + 1)
                if nested is not None:
                    return nested

        elif isinstance(source, list):
            for value in source:
                nested = TornClient._find_first_int_by_keys(value, keys, depth + 1)
                if nested is not None:
                    return nested

        return None

    async def _get_optional_first_supported(self, path: str, selections_candidates: list[str]) -> dict[str, Any] | None:
        rejected: list[tuple[str, int | None, str]] = []
        for selection in selections_candidates:
            try:
                payload = await self._get_with_v2_fallback(path, {"selections": selection})
                if isinstance(payload, dict):
                    return payload
            except TornApiError as exc:
                if exc.code in {4, 16, 22, 23}:
                    rejected.append((selection, exc.code, exc.message))
                    continue
                raise

        if rejected:
            details = ", ".join([f"{selection}: code={code} message={message}" for selection, code, message in rejected])
            self._log_diagnostic_once(
                f"optional-selection-failed:{path}:{'|'.join(selections_candidates)}:{details}",
                "Optional Torn selection(s) not available for %s -> %s",
                path,
                details,
            )
        return None

    def _log_diagnostic_once(self, key: str, message: str, *args: Any) -> None:
        if key in self._diagnostics_once:
            return
        self._diagnostics_once.add(key)
        logger.warning(message, *args)

    async def fetch_faction_data(self, faction_id: int) -> dict[str, Any]:
        path = "faction" if faction_id <= 0 else f"faction/{faction_id}"
        payload = await self._get(path, {"selections": "basic,members"})

        members = payload.get("members", {})
        online_count = 0
        critical_members: list[dict[str, str]] = []

        if isinstance(members, dict):
            for member_id, details in members.items():
                if not isinstance(details, dict):
                    continue
                status = details.get("status", {}) if isinstance(details.get("status"), dict) else {}
                state = str(status.get("state", ""))
                description = str(status.get("description", ""))

                if state.lower() == "online":
                    online_count += 1

                if any(keyword in description.lower() for keyword in ("hospital", "travel", "jail")):
                    critical_members.append(
                        {
                            "member_id": str(member_id),
                            "name": str(details.get("name", f"Member {member_id}")),
                            "status": description or state,
                        }
                    )

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": str(payload.get("name", "Unknown Faction")),
            "members_total": int(payload.get("members", 0) if isinstance(payload.get("members"), int) else len(members or {})),
            "members_online": online_count,
            "respect": int(payload.get("respect", 0)),
            "chain_current": int(payload.get("chain", {}).get("current", 0)) if isinstance(payload.get("chain"), dict) else 0,
            "chain_timeout": int(payload.get("chain", {}).get("timeout", 0)) if isinstance(payload.get("chain"), dict) else 0,
            "critical_members": critical_members[:10],
        }

    @staticmethod
    def _extract_events(events_payload: Any) -> list[dict[str, str]]:
        events: list[dict[str, str]] = []
        if not isinstance(events_payload, dict):
            return events

        for event_id, details in events_payload.items():
            if isinstance(details, dict):
                text = str(details.get("event", details.get("text", "")))
                timestamp = str(details.get("timestamp", datetime.now(timezone.utc).isoformat()))
            else:
                text = str(details)
                timestamp = datetime.now(timezone.utc).isoformat()

            if text:
                events.append({"event_id": str(event_id), "timestamp": timestamp, "text": text})

        return events
