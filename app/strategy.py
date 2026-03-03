from __future__ import annotations

from statistics import mean, pstdev


class StrategyEngine:
    def __init__(self, window: int, volatility_weight: float, min_drop_percent: float) -> None:
        self.window = max(4, window)
        self.volatility_weight = max(0.0, volatility_weight)
        self.min_drop_percent = max(0.5, min_drop_percent)

    def dynamic_drop_threshold(self, prices: list[int]) -> float:
        if len(prices) < 3:
            return self.min_drop_percent

        sample = prices[-self.window :]
        avg = mean(sample)
        if avg <= 0:
            return self.min_drop_percent
        volatility_pct = (pstdev(sample) / avg) * 100
        return self.min_drop_percent + volatility_pct * self.volatility_weight

    def signal_for_series(self, prices: list[int]) -> dict:
        if len(prices) < self.window:
            return {"has_signal": False, "reason": "not_enough_data"}

        sample = prices[-self.window :]
        moving_avg = mean(sample)
        current = prices[-1]
        threshold = self.dynamic_drop_threshold(prices)
        drop_percent = ((moving_avg - current) / moving_avg) * 100 if moving_avg > 0 else 0

        return {
            "has_signal": drop_percent >= threshold,
            "moving_average": round(moving_avg, 2),
            "current_price": current,
            "drop_percent": round(drop_percent, 2),
            "dynamic_threshold": round(threshold, 2),
        }

    def backtest(self, prices: list[int], horizon_steps: int, target_profit_percent: float) -> dict:
        horizon = max(1, horizon_steps)
        target = max(0.1, target_profit_percent)

        if len(prices) < self.window + horizon + 1:
            return {
                "samples": 0,
                "signals": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_return_percent": 0.0,
            }

        signals = 0
        wins = 0
        losses = 0
        returns: list[float] = []

        for idx in range(self.window, len(prices) - horizon):
            history = prices[: idx + 1]
            signal = self.signal_for_series(history)
            if not signal["has_signal"]:
                continue

            entry = prices[idx]
            future_window = prices[idx + 1 : idx + 1 + horizon]
            if not future_window:
                continue

            best_future = max(future_window)
            realized = ((best_future - entry) / entry) * 100 if entry > 0 else 0

            signals += 1
            returns.append(realized)
            if realized >= target:
                wins += 1
            else:
                losses += 1

        avg_return = mean(returns) if returns else 0.0
        win_rate = (wins / signals) * 100 if signals else 0.0

        return {
            "samples": len(prices),
            "signals": signals,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "avg_return_percent": round(avg_return, 2),
            "target_profit_percent": target,
            "horizon_steps": horizon,
        }
