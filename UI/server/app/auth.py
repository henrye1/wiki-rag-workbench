"""Optional shared-password login. Enabled when UI_PASSWORD is set (e.g. before exposing the UI through a tunnel).

The session is an HMAC-signed cookie; protected paths are /api/* (except login/session) and /view/*.
"""
import asyncio
import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE = "wb_session"
MAX_AGE = 7 * 24 * 3600
OPEN_PATHS = ("/api/auth/",)


def enabled() -> bool:
    return bool(get_settings().ui_password)


def _secret() -> bytes:
    s = get_settings()
    # Derived from the password, so changing UI_PASSWORD logs everyone out
    return hashlib.sha256(f"wb:{s.ui_password}:{s.session_secret}".encode()).digest()


def _sign(expires: int) -> str:
    sig = hmac.new(_secret(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, _, _sig = token.partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(token, _sign(int(exp)))


class LoginIn(BaseModel):
    password: str


@router.get("/session")
async def session(request: Request):
    return {"auth_required": enabled(), "authenticated": not enabled() or valid(request.cookies.get(COOKIE))}


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    if not enabled():
        return {"ok": True}
    if not secrets.compare_digest(body.password.encode(), get_settings().ui_password.encode()):
        await asyncio.sleep(1.5)  # slow down guessing
        raise HTTPException(401, "Wrong password")
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(COOKIE, _sign(int(time.time()) + MAX_AGE), max_age=MAX_AGE, httponly=True, samesite="lax", secure=https)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        protected = (path.startswith("/api/") and not path.startswith(OPEN_PATHS)) or path.startswith("/view")
        if enabled() and protected and not valid(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "Login required"}, status_code=401)
        return await call_next(request)
