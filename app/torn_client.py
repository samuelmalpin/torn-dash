from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiohttp


class TornClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25))

    async def stop(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("TornClient not started")

        enriched_params = {**params, "key": self.api_key}
        url = f"{self.base_url}/{path.lstrip('/')}"

        async with self._session.get(url, params=enriched_params) as response:
            response.raise_for_status()
            payload = await response.json()
            if "error" in payload:
                raise RuntimeError(f"Torn API error: {payload['error']}")
            return payload

    async def fetch_user_data(self) -> dict[str, Any]:
        payload = await self._get("user", {"selections": "profile,bars,money,points,events"})

        bars = payload.get("bars", {})
        money_data = payload.get("money", {})
        points_data = payload.get("points", {})

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": int(payload.get("level", 0)),
            "energy_current": int(bars.get("energy", {}).get("current", 0)),
            "energy_max": int(bars.get("energy", {}).get("maximum", 0)),
            "nerve_current": int(bars.get("nerve", {}).get("current", 0)),
            "nerve_max": int(bars.get("nerve", {}).get("maximum", 0)),
            "money": int(money_data.get("money_onhand", payload.get("money_onhand", 0))),
            "points": int(points_data.get("points", payload.get("points", 0))),
            "events": self._extract_events(payload.get("events", {})),
        }

    async def fetch_market_price(self, item_id: int) -> dict[str, Any] | None:
        payload = await self._get(f"market/{item_id}", {"selections": "bazaar,itemmarket"})

        candidates: list[int] = []

        for key in ("bazaar", "itemmarket"):
            section = payload.get(key, {})
            if isinstance(section, dict):
                for _, listing in section.items():
                    price = listing.get("cost") or listing.get("price")
                    if isinstance(price, (int, float)) and price > 0:
                        candidates.append(int(price))
            elif isinstance(section, list):
                for listing in section:
                    if not isinstance(listing, dict):
                        continue
                    price = listing.get("cost") or listing.get("price")
                    if isinstance(price, (int, float)) and price > 0:
                        candidates.append(int(price))

        if not candidates:
            return None

        item_name = payload.get("name") or payload.get("item", {}).get("name") or f"Item {item_id}"

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "item_id": item_id,
            "item_name": item_name,
            "lowest_price": min(candidates),
        }

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
