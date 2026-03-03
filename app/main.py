from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from statistics import mean

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status # pyright: ignore[reportMissingImports]
from fastapi.responses import FileResponse, RedirectResponse # pyright: ignore[reportMissingImports]
from fastapi.staticfiles import StaticFiles # pyright: ignore[reportMissingImports]
from pydantic import BaseModel # pyright: ignore[reportMissingImports]

from app.auth import authenticate_user, create_session_token, decode_session_token, is_auth_secret_secure
from app.config import settings
from app.services import TornNexusService
from app.torn_client import TornApiError

service = TornNexusService()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await service.start()
    yield
    await service.stop()


app = FastAPI(title="Torn Nexus Bot", version="1.0.0", lifespan=lifespan)

static_dir = Path(__file__).parent / "static"


class AssetOnlyStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        normalized = path.lstrip("/").lower()
        if normalized.endswith(".html"):
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        return await super().get_response(path, scope)


app.mount("/static", AssetOnlyStaticFiles(directory=str(static_dir)), name="static")


class LoginPayload(BaseModel):
    username: str
    password: str


def get_current_user(request: Request) -> dict:
    token = request.cookies.get("torn_session", "")
    payload = decode_session_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return payload


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def get_authenticated_user(user: dict = Depends(get_current_user)) -> dict:
    return user


def _compute_opportunities_payload() -> list[dict]:
    opportunities_payload: list[dict] = []
    for item_id in service.get_effective_tracked_item_ids():
        series = service.storage.get_market_prices_for_item(item_id=item_id, limit=220)
        if not series:
            opportunities_payload.append(
                {
                    "item_id": item_id,
                    "item_name": f"Item {item_id}",
                    "action": "NO_DATA",
                    "confidence": 0.0,
                    "current_price": 0,
                    "moving_average": 0.0,
                    "drop_percent": 0.0,
                    "threshold_percent": 0.0,
                    "expected_return": 0,
                    "expected_return_percent": 0.0,
                    "samples": 0,
                    "updated_at": None,
                }
            )
            continue

        prices = [int(row["lowest_price"]) for row in series if int(row.get("lowest_price", 0)) > 0]
        item_name = str(series[-1].get("item_name") or f"Item {item_id}")

        if len(prices) < service.strategy.window:
            current_price = prices[-1] if prices else int(series[-1].get("lowest_price", 0) or 0)
            opportunities_payload.append(
                {
                    "item_id": item_id,
                    "item_name": item_name,
                    "action": "WAIT_DATA",
                    "confidence": 35.0,
                    "current_price": current_price,
                    "moving_average": round(float(mean(prices)) if prices else 0.0, 2),
                    "drop_percent": 0.0,
                    "threshold_percent": round(float(settings.strategy_min_drop_percent), 2),
                    "expected_return": 0,
                    "expected_return_percent": 0.0,
                    "samples": len(prices),
                    "min_samples_required": service.strategy.window,
                    "updated_at": series[-1].get("timestamp"),
                }
            )
            continue

        signal = service.strategy.signal_for_series(prices)
        current_price = int(signal.get("current_price", prices[-1]))
        moving_average = float(signal.get("moving_average", mean(prices[-service.strategy.window :])))
        threshold = float(signal.get("dynamic_threshold", settings.strategy_min_drop_percent))
        drop_percent = float(signal.get("drop_percent", 0.0))
        expected_return = max(0.0, moving_average - current_price)
        expected_return_pct = (expected_return / current_price * 100) if current_price > 0 else 0.0

        confidence = 50 + min(40, max(0.0, drop_percent - threshold) * 4)
        if signal.get("has_signal"):
            action = "BUY"
        elif drop_percent >= (threshold * 0.65):
            action = "WATCH"
            confidence = min(confidence, 74)
        else:
            action = "SKIP"
            confidence = min(confidence, 59)

        opportunities_payload.append(
            {
                "item_id": item_id,
                "item_name": item_name,
                "action": action,
                "confidence": round(confidence, 1),
                "current_price": current_price,
                "moving_average": round(moving_average, 2),
                "drop_percent": round(drop_percent, 2),
                "threshold_percent": round(threshold, 2),
                "expected_return": int(expected_return),
                "expected_return_percent": round(expected_return_pct, 2),
                "samples": len(prices),
                "updated_at": series[-1].get("timestamp"),
            }
        )

    opportunities_payload.sort(
        key=lambda row: (
            row["action"] != "BUY",
            row["action"] == "NO_DATA",
            -float(row["confidence"]),
            -float(row["expected_return"]),
        )
    )
    return opportunities_payload


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(static_dir / "login.html")


@app.get("/")
def root_page(request: Request) -> RedirectResponse:
    token = request.cookies.get("torn_session", "")
    payload = decode_session_token(token)
    if payload:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@app.get("/dashboard", response_model=None)
def dashboard(request: Request) -> FileResponse | RedirectResponse:
    token = request.cookies.get("torn_session", "")
    payload = decode_session_token(token)
    if not payload:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return FileResponse(static_dir / "index.html")


@app.post("/api/auth/login")
def login(payload: LoginPayload, request: Request, response: Response) -> dict:
    if not is_auth_secret_secure():
        logger.error("Refusing login: AUTH_SECRET is insecure. Set a random secret with at least 32 characters.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable: server secret misconfiguration.",
        )

    profile = authenticate_user(payload.username.strip(), payload.password)
    if not profile:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_session_token(profile["username"], profile["role"])
    response.set_cookie(
        key="torn_session",
        value=token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
        max_age=settings.auth_session_hours * 3600,
    )
    return {"ok": True, "username": profile["username"], "role": profile["role"]}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie("torn_session", path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(get_authenticated_user)) -> dict:
    return {"username": user.get("username"), "role": user.get("role")}


@app.get("/api/health")
def health(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    tracked_items = service.get_effective_tracked_item_ids()
    return {
        "status": "ok",
        "torn_configured": bool(settings.torn_api_key),
        "tracked_items": tracked_items,
        "history_points": settings.dashboard_history_points,
        "faction_id": settings.faction_id,
        "trading_budget_default": settings.trading_budget_default,
        "trading_max_positions": settings.trading_max_positions,
        "auto_discovery_enabled": settings.auto_discovery_enabled,
        "manual_tracked_items": settings.tracked_item_ids,
    }


@app.get("/api/overview")
def overview(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    return service.storage.get_latest_overview()


@app.get("/api/market")
def market(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    return {"history": service.storage.get_market_history()}


@app.post("/api/market/poll-now")
async def market_poll_now(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    try:
        result = await service.refresh_market_now()
        return {"ok": True, **result}
    except TornApiError as exc:
        if exc.code == 5:
            return {
                "ok": False,
                "error": "rate_limited",
                "detail": "Too many requests from Torn API. Try again later.",
            }
        raise


@app.get("/api/timeseries")
def timeseries(
    points: int = Query(default=settings.dashboard_history_points, ge=12, le=300),
    user: dict = Depends(get_authenticated_user),
) -> dict:
    _ = user
    return {
        "points": service.storage.get_user_timeseries(limit=points),
    }


@app.get("/api/insights")
def insights(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    tracked_items = service.get_effective_tracked_item_ids()
    return {
        "market": service.storage.get_market_insights(tracked_items),
    }


@app.get("/api/opportunities")
def opportunities(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    opportunities_payload = _compute_opportunities_payload()

    return {
        "items": opportunities_payload[:8],
        "summary": {
            "buy": sum(1 for row in opportunities_payload if row["action"] == "BUY"),
            "watch": sum(1 for row in opportunities_payload if row["action"] == "WATCH"),
            "skip": sum(1 for row in opportunities_payload if row["action"] == "SKIP"),
            "wait_data": sum(1 for row in opportunities_payload if row["action"] == "WAIT_DATA"),
            "no_data": sum(1 for row in opportunities_payload if row["action"] == "NO_DATA"),
        },
    }


@app.get("/api/trading/plan")
def trading_plan(
    budget: int = Query(default=settings.trading_budget_default, ge=10000, le=2_000_000_000),
    max_positions: int = Query(default=settings.trading_max_positions, ge=1, le=20),
    user: dict = Depends(get_authenticated_user),
) -> dict:
    _ = user
    opportunities_payload = _compute_opportunities_payload()

    candidates = [
        row
        for row in opportunities_payload
        if row.get("action") in {"BUY", "WATCH"} and int(row.get("current_price", 0)) > 0
    ]
    candidates.sort(
        key=lambda row: (
            row.get("action") != "BUY",
            -(float(row.get("confidence", 0.0)) + float(row.get("expected_return_percent", 0.0))),
        )
    )

    remaining = int(budget)
    slots = max(1, int(max_positions))
    plan_items: list[dict] = []

    for candidate in candidates:
        if remaining <= 0 or len(plan_items) >= slots:
            break

        price = int(candidate.get("current_price", 0))
        if price <= 0:
            continue

        open_slots = max(1, slots - len(plan_items))
        slot_budget = max(price, remaining // open_slots)
        quantity = slot_budget // price
        if quantity <= 0:
            continue

        spend = quantity * price
        if spend > remaining:
            quantity = remaining // price
            spend = quantity * price
        if quantity <= 0:
            continue

        remaining -= spend
        plan_items.append(
            {
                "item_id": candidate["item_id"],
                "item_name": candidate["item_name"],
                "action": candidate["action"],
                "confidence": candidate["confidence"],
                "unit_price": price,
                "quantity": quantity,
                "allocated": spend,
                "expected_return_unit": int(candidate.get("expected_return", 0)),
                "expected_return_total": int(candidate.get("expected_return", 0)) * quantity,
                "expected_return_percent": candidate.get("expected_return_percent", 0.0),
            }
        )

    spent = int(budget) - remaining
    return {
        "mode": "simulation_only",
        "executable": False,
        "budget": int(budget),
        "spent": spent,
        "remaining": remaining,
        "positions": len(plan_items),
        "items": plan_items,
        "note": "Torn API is read-only for this app: this is a trading plan assistant, not automatic order execution.",
    }


@app.get("/api/market/series")
def market_series(item_id: int = Query(..., ge=1), limit: int = Query(default=120, ge=20, le=500), user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    return {"series": service.storage.get_market_prices_for_item(item_id=item_id, limit=limit)}


@app.get("/api/faction/war-room")
def faction_war_room(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    return {
        "snapshot": service.storage.get_latest_faction_snapshot(),
    }


@app.get("/api/strategy/backtest")
def strategy_backtest(item_id: int = Query(..., ge=1), user: dict = Depends(require_admin)) -> dict:
    _ = user
    series = service.storage.get_market_prices_for_item(item_id=item_id, limit=500)
    prices = [int(row["lowest_price"]) for row in series]

    report = service.strategy.backtest(
        prices=prices,
        horizon_steps=settings.backtest_horizon_steps,
        target_profit_percent=settings.backtest_profit_target_percent,
    )
    latest_signal = service.strategy.signal_for_series(prices) if prices else {"has_signal": False, "reason": "no_data"}

    return {
        "item_id": item_id,
        "report": report,
        "latest_signal": latest_signal,
    }
