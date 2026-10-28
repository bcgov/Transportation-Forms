"""Authenticated best-effort Staff detail and link signals."""

import asyncio
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials

from backend.auth.dependencies import get_current_user
from backend.services.daily_engagement import (
    dispatcher,
    record_daily_engagement,
)
from backend.services.engagement_cache import cache
from shared.engagement_signal import (
    RESPONSE_HEADERS,
    parse_signal,
    reject,
    same_origin,
)

router = APIRouter(prefix="/engagement", tags=["engagement"])
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


@router.post("/signal")
async def signal(
    request: Request, _user=Depends(_authenticated_staff)
) -> JSONResponse:
    if not same_origin(request, os.environ.get("STAFF_ENGAGEMENT_ORIGIN", "")):
        return reject(403)
    data = await parse_signal(request, "form_id")
    if isinstance(data, JSONResponse):
        return data
    value = data["form_id"]
    if not isinstance(value, str) or len(value) != 36:
        return reject(400)
    try:
        form_id = UUID(value)
    except ValueError:
        return reject(400)
    metric = data["metric"]
    if str(form_id) != value.lower() or not isinstance(metric, str):
        return reject(400)
    if not cache.eligible(form_id, metric):
        return reject(404)
    future = dispatcher.submit(
        record_daily_engagement, form_id, metric, "Staff"
    )
    if future is None:
        return reject(503)
    try:
        await asyncio.shield(asyncio.wrap_future(future))
    except Exception:
        return reject(503)
    return JSONResponse(
        {"accepted": True}, status_code=202, headers=RESPONSE_HEADERS
    )
