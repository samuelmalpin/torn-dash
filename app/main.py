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


class EmergencyStopPayload(BaseModel):
    enabled: bool


def get_current_user(request: Request) -> dict:
    token = request.cookies.get("torn_session", "")
    payload = decode_session_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return payload


def get_authenticated_user(user: dict = Depends(get_current_user)) -> dict:
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
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
    return {
        "status": "ok",
        "torn_configured": bool(settings.torn_api_key),
        "history_points": settings.dashboard_history_points,
        "faction_id": settings.faction_id,
    }


@app.get("/api/overview")
def overview(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    return service.storage.get_latest_overview()


@app.get("/api/timeseries")
def timeseries(
    points: int = Query(default=settings.dashboard_history_points, ge=12, le=300),
    user: dict = Depends(get_authenticated_user),
) -> dict:
    _ = user
    return {
        "points": service.storage.get_user_timeseries(limit=points),
    }


@app.get("/api/faction/war-room")
def faction_war_room(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    return {
        "snapshot": service.storage.get_latest_faction_snapshot(),
    }


@app.get("/api/automation/status")
def automation_status(user: dict = Depends(get_authenticated_user)) -> dict:
    _ = user
    return service.get_automation_status()


@app.get("/api/automation/logs")
def automation_logs(
    limit: int = Query(default=80, ge=1, le=500),
    user: dict = Depends(get_authenticated_user),
) -> dict:
    _ = user
    return {"items": service.get_automation_logs(limit=limit)}


@app.post("/api/automation/start")
async def automation_start(user: dict = Depends(require_admin)) -> dict:
    _ = user
    started = await service.start_automation()
    return {"ok": started, "status": service.get_automation_status()}


@app.post("/api/automation/stop")
async def automation_stop(user: dict = Depends(require_admin)) -> dict:
    _ = user
    await service.stop_automation()
    return {"ok": True, "status": service.get_automation_status()}


@app.post("/api/automation/emergency-stop")
async def automation_emergency_stop(payload: EmergencyStopPayload, user: dict = Depends(require_admin)) -> dict:
    _ = user
    await service.set_automation_emergency_stop(payload.enabled)
    return {"ok": True, "status": service.get_automation_status()}
