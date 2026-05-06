"""Shared problem+json helpers (RFC 7807).

All public-backend error responses use ``application/problem+json`` so
clients (and crawlers) get a stable, documented error contract.  Stack
traces, library versions, and file paths are NEVER included — see
``main.py`` for the registered exception handlers and US-014 AC14.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from starlette.responses import JSONResponse


def problem_response(
    *,
    status: int,
    title: str,
    detail: str,
    instance: Optional[str] = None,
    type_: str = "about:blank",
    extra: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> JSONResponse:
    """Build an ``application/problem+json`` :class:`JSONResponse`."""
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status,
        "detail": detail,
    }
    if instance:
        body["instance"] = instance
    if extra:
        for k, v in extra.items():
            if k not in body:
                body[k] = v
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
        headers=dict(headers) if headers else None,
    )
