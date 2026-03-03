from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    energy_current INTEGER NOT NULL,
                    energy_max INTEGER NOT NULL,
                    nerve_current INTEGER NOT NULL,
                    nerve_max INTEGER NOT NULL,
                    money INTEGER NOT NULL,
                    points INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS market_prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    item_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    lowest_price INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS torn_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS faction_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    name TEXT NOT NULL,
                    members_total INTEGER NOT NULL,
                    members_online INTEGER NOT NULL,
                    respect INTEGER NOT NULL,
                    chain_current INTEGER NOT NULL,
                    chain_timeout INTEGER NOT NULL,
                    critical_members_json TEXT NOT NULL
                );
                """
            )

    def add_user_snapshot(self, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_snapshots (
                    timestamp, level, energy_current, energy_max,
                    nerve_current, nerve_max, money, points
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["timestamp"],
                    payload["level"],
                    payload["energy_current"],
                    payload["energy_max"],
                    payload["nerve_current"],
                    payload["nerve_max"],
                    payload["money"],
                    payload["points"],
                ),
            )

    def add_market_price(self, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO market_prices (timestamp, item_id, item_name, lowest_price)
                VALUES (?, ?, ?, ?)
                """,
                (
                    payload["timestamp"],
                    payload["item_id"],
                    payload["item_name"],
                    payload["lowest_price"],
                ),
            )

    def add_alert(self, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alerts (timestamp, kind, message)
                VALUES (?, ?, ?)
                """,
                (payload["timestamp"], payload["kind"], payload["message"]),
            )

    def add_events(self, events: list[dict[str, Any]]) -> int:
        inserted = 0
        with self._connect() as conn:
            for event in events:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO torn_events (event_id, timestamp, text)
                    VALUES (?, ?, ?)
                    """,
                    (event["event_id"], event["timestamp"], event["text"]),
                )
                if cursor.rowcount > 0:
                    inserted += 1
        return inserted

    def get_latest_overview(self) -> dict[str, Any]:
        with self._connect() as conn:
            snapshot = conn.execute(
                """
                SELECT * FROM user_snapshots
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()

            latest_alerts = conn.execute(
                """
                SELECT timestamp, kind, message FROM alerts
                ORDER BY id DESC LIMIT 10
                """
            ).fetchall()

            latest_events = conn.execute(
                """
                SELECT event_id, timestamp, text FROM torn_events
                ORDER BY id DESC LIMIT 10
                """
            ).fetchall()

        return {
            "snapshot": dict(snapshot) if snapshot else None,
            "alerts": [dict(row) for row in latest_alerts],
            "events": [dict(row) for row in latest_events],
        }

    def get_market_history(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, item_id, item_name, lowest_price
                FROM market_prices
                ORDER BY id DESC LIMIT 100
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_average_price(self, item_id: int, sample_size: int = 8) -> float | None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT lowest_price FROM market_prices
                WHERE item_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (item_id, sample_size),
            ).fetchall()

        prices = [row["lowest_price"] for row in rows]
        if not prices:
            return None
        return sum(prices) / len(prices)

    def get_market_prices_for_item(self, item_id: int, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, item_id, item_name, lowest_price
                FROM market_prices
                WHERE item_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (item_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_user_timeseries(self, limit: int = 48) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    timestamp,
                    level,
                    energy_current,
                    energy_max,
                    nerve_current,
                    nerve_max,
                    money,
                    points
                FROM user_snapshots
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_market_insights(self, item_ids: list[int], sample_size: int = 12) -> list[dict[str, Any]]:
        insights: list[dict[str, Any]] = []

        with self._connect() as conn:
            for item_id in item_ids:
                recent = conn.execute(
                    """
                    SELECT item_name, lowest_price
                    FROM market_prices
                    WHERE item_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (item_id, sample_size),
                ).fetchall()

                if not recent:
                    continue

                latest_price = int(recent[0]["lowest_price"])
                item_name = str(recent[0]["item_name"])
                prices = [int(row["lowest_price"]) for row in recent]
                avg_price = sum(prices) / len(prices)
                delta_percent = ((latest_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0

                insights.append(
                    {
                        "item_id": item_id,
                        "item_name": item_name,
                        "latest_price": latest_price,
                        "average_price": round(avg_price, 2),
                        "delta_percent": round(delta_percent, 2),
                    }
                )

        insights.sort(key=lambda item: item["delta_percent"])
        return insights

    def add_faction_snapshot(self, payload: dict[str, Any]) -> None:
        import json

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO faction_snapshots (
                    timestamp, name, members_total, members_online,
                    respect, chain_current, chain_timeout, critical_members_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["timestamp"],
                    payload["name"],
                    payload["members_total"],
                    payload["members_online"],
                    payload["respect"],
                    payload["chain_current"],
                    payload["chain_timeout"],
                    json.dumps(payload.get("critical_members", [])),
                ),
            )

    def get_latest_faction_snapshot(self) -> dict[str, Any] | None:
        import json

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT timestamp, name, members_total, members_online, respect, chain_current, chain_timeout, critical_members_json
                FROM faction_snapshots
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        if not row:
            return None

        payload = dict(row)
        payload["critical_members"] = json.loads(payload.pop("critical_members_json", "[]"))
        return payload
