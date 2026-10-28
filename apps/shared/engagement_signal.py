"""Common strict request boundary for Staff and Public engagement signals."""

import json
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

MAX_BODY_BYTES = 1024
ALLOWED_METRICS = frozenset({"detail_view", "link_click"})
RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def origin(
    value: str, *, referer: bool = False
) -> tuple[str, str, int] | None:
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


def same_origin(request: Request, expected_url: str) -> bool:
    expected = origin(expected_url)
    header = request.headers.get("origin")
    if header is not None:
        return expected is not None and origin(header) == expected
    referer = request.headers.get("referer")
    return (
        referer is not None
        and expected is not None
        and origin(referer, referer=True) == expected
    )


def reject(status: int) -> JSONResponse:
    return JSONResponse(
        {"accepted": False}, status_code=status, headers=RESPONSE_HEADERS
    )


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate field")
    return result


async def parse_signal(
    request: Request, identifier: str
) -> dict[str, object] | JSONResponse:
    if request.headers.get("content-type") != "application/json":
        return reject(415)
    try:
        if int(request.headers.get("content-length", "0")) > MAX_BODY_BYTES:
            return reject(413)
    except ValueError:
        return reject(400)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return reject(413)
    try:
        data = json.loads(body, object_pairs_hook=_unique_pairs)
        if (
            not isinstance(data, dict)
            or set(data) != {identifier, "metric"}
            or not isinstance(data["metric"], str)
            or data["metric"] not in ALLOWED_METRICS
        ):
            return reject(400)
    except (ValueError, UnicodeDecodeError, TypeError):
        return reject(400)
    return data
