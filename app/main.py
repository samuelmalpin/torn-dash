from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status # pyright: ignore[reportMissingImports]
from fastapi.responses import FileResponse, RedirectResponse # pyright: ignore[reportMissingImports]
from fastapi.staticfiles import StaticFiles # pyright: ignore[reportMissingImports]
from pydantic import BaseModel # pyright: ignore[reportMissingImports]

from app.auth import authenticate_user, create_session_token, decode_session_token, is_auth_secret_secure
from app.config import settings
from app.services import TornNexusService

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


@app.get("/dashboard")
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
    return {
        "status": "ok",
        "torn_configured": bool(settings.torn_api_key),
        "tracked_items": settings.tracked_item_ids,
        "history_points": settings.dashboard_history_points,
        "faction_id": settings.faction_id,
    }


@app.get("/api/overview")
def overview(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    return service.storage.get_latest_overview()


@app.get("/api/market")
def market(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    return {"history": service.storage.get_market_history()}


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
    return {
        "market": service.storage.get_market_insights(settings.tracked_item_ids),
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
