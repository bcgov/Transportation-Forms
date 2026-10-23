"""Authenticated best-effort Staff detail and link signals."""

import asyncio
import json
import os
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials

from backend.auth.dependencies import get_current_user
from backend.services.daily_engagement import record_daily_engagement
from backend.services.engagement_cache import cache

router = APIRouter(prefix="/engagement", tags=["engagement"])
MAX_BODY_BYTES = 1024
ALLOWED_METRICS = frozenset({"detail_view", "link_click"})
RESPONSE_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
bearer = HTTPBearer(auto_error=False)


async def _authenticated_staff(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    if credentials is not None:
        try:
            return await get_current_user(credentials)
        except HTTPException:
            pass
    raise HTTPException(
        status_code=401,
        detail="Unauthorized",
        headers={**RESPONSE_HEADERS, "WWW-Authenticate": "Bearer"},
    )


def _origin(value: str, *, referer: bool = False) -> tuple[str, str, int] | None:
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or (not referer and (parts.path or parts.query or parts.fragment))
        ):
            return None
        return (
            parts.scheme,
            parts.hostname.lower(),
            parts.port or (443 if parts.scheme == "https" else 80),
        )
    except ValueError:
        return None


def _same_origin(request: Request) -> bool:
    expected = _origin(os.environ.get("STAFF_ENGAGEMENT_ORIGIN", ""))
    header = request.headers.get("origin")
    if header is not None:
        return _origin(header) == expected and expected is not None
    referer = request.headers.get("referer")
    return (
        referer is not None
        and _origin(referer, referer=True) == expected
        and expected is not None
    )


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate field")
    return result


def _reject(status: int) -> JSONResponse:
    return JSONResponse(
        {"accepted": False}, status_code=status, headers=RESPONSE_HEADERS
    )


@router.post("/signal")
async def signal(request: Request, _user=Depends(_authenticated_staff)) -> JSONResponse:
    if not _same_origin(request):
        return _reject(403)
    if request.headers.get("content-type") != "application/json":
        return _reject(415)
    try:
        if int(request.headers.get("content-length", "0")) > MAX_BODY_BYTES:
            return _reject(413)
    except ValueError:
        return _reject(400)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return _reject(413)
    try:
        data = json.loads(body, object_pairs_hook=_unique_pairs)
        if not isinstance(data, dict) or set(data) != {"form_id", "metric"}:
            return _reject(400)
        value = data["form_id"]
        metric = data["metric"]
        if (
            not isinstance(value, str)
            or len(value) != 36
            or not isinstance(metric, str)
        ):
            return _reject(400)
        form_id = UUID(value)
        if str(form_id) != value.lower() or metric not in ALLOWED_METRICS:
            return _reject(400)
    except (ValueError, UnicodeDecodeError, TypeError):
        return _reject(400)
    if not cache.eligible(form_id, metric):
        return _reject(404)
    try:
        await asyncio.to_thread(record_daily_engagement, form_id, metric, "Staff")
    except Exception:
        return _reject(503)
    return JSONResponse({"accepted": True}, status_code=202, headers=RESPONSE_HEADERS)
