"""Audit-event emission for the public-backend (FEAT-0005).

Currently only download events are audited (US-004 / US-014 AC6).  The
emitter is a thin wrapper around :mod:`structlog` so we can:

* Pin a stable event-type vocabulary (``public_form_download``) for
  downstream log queries / SIEM rules.
* Centralise the redaction policy: never log the ``X-Internal-Auth``
  header, never log raw S3 keys (we only log ``form_number`` +
  ``filename`` which are already public values).
* Make the call sites self-documenting and unit-testable.
"""

from __future__ import annotations

from typing import Optional

import structlog

from starlette.requests import Request


_audit = structlog.get_logger("public_backend.audit")


def _client_ip(request: Request) -> Optional[str]:
    """Return the best-effort real client IP.

    NGINX at the edge sets ``X-Real-IP`` from the OpenShift router CIDR;
    we trust that header here and never trust raw ``X-Forwarded-For``
    for security-sensitive decisions (rate-limit keying lives at NGINX).
    """
    real = request.headers.get("X-Real-IP")
    if real:
        return real
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # Only the left-most token is the original client.
        return xff.split(",", 1)[0].strip() or None
    if request.client and request.client.host:
        return request.client.host
    return None


def log_form_download(
    request: Request,
    *,
    form_number: str,
    filename: Optional[str],
) -> None:
    """Emit an audit-log entry for a public form download attempt.

    Privacy:
      * No PII collected (the public surface is unauthenticated).
      * Shared secret never read from headers; only ``X-Real-IP`` and
        ``User-Agent`` are recorded.
      * S3 object keys are not logged.
    """
    _audit.info(
        "public_form_download",
        form_number=form_number,
        filename=filename,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        request_id=getattr(request.state, "request_id", None),
    )
