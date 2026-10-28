"""Anonymous, cache-gated Public detail and source-link signals."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config import settings
from daily_engagement import dispatcher, record_daily_engagement
from engagement_cache import cache
from shared.engagement_signal import (
    RESPONSE_HEADERS,
    parse_signal,
    reject,
    same_origin,
)

router = APIRouter(prefix="/api/public/v1/engagement", tags=["engagement"])


@router.post("/signal")
async def signal(request: Request) -> JSONResponse:
    if not same_origin(request, settings.PUBLIC_BASE_URL.rstrip("/")):
        return reject(403)
    data = await parse_signal(request, "form_number")
    if isinstance(data, JSONResponse):
        return data
    number = data["form_number"]
    if (
        not isinstance(number, str)
        or not 1 <= len(number) <= 70
        or number != number.strip()
        or not all(
            character.isalnum() or character == " " for character in number
        )
    ):
        return reject(400)
    metric = data["metric"]
    if not isinstance(metric, str):
        return reject(400)
    form_id = cache.resolve(number, metric)
    if form_id is None:
        return reject(404)
    future = dispatcher.submit(
        record_daily_engagement, form_id, metric, "Public"
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
