"""S3-compatible object storage service.

Provides file upload/delete operations backed by any S3-compatible object store
(MinIO for local development, custom S3 service in production).

Uses boto3 (already in requirements.txt) with an endpoint_url override so the
same code works with both MinIO and real AWS S3.
"""

import json
import uuid
import logging
import hashlib
from typing import Tuple, Iterator


class S3ObjectNotFound(Exception):
    """Raised by ``stream_object`` when the requested object does not exist.

    The exception message intentionally does NOT include the S3 object key
    so that callers can re-raise / log safely without leaking storage keys.
    """

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from backend.config import settings

logger = logging.getLogger(__name__)


# ─── FEAT-0002: MIME-to-file-type mapping ─────────────────────────────────────

MIME_TYPE_MAP: dict[str, str] = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/csv": "csv",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "application/zip": "zip",
}


def derive_file_type(content_type: str) -> str:
    """Derive a short file-type label from a MIME content type.

    Returns a lowercase extension string (e.g. ``"pdf"``, ``"docx"``).
    Returns ``"unknown"`` for any MIME type not in the supported mapping.
    """
    normalized = (content_type or "").strip().lower().split(";")[0].strip()
    return MIME_TYPE_MAP.get(normalized, "unknown")


def _get_s3_client():
    """Return a boto3 S3 client pointed at the configured S3-compatible endpoint."""
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        verify=settings.S3_VERIFY_TLS,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket_exists() -> None:
    """Create the configured bucket if it does not already exist, and ensure
    a public-read bucket policy is applied.

    Modern MinIO (2022+) disables S3 object ACLs by default.  Public read
    access must be granted via a bucket policy instead.
    """
    client = _get_s3_client()
    bucket = settings.S3_BUCKET
    try:
        client.head_bucket(Bucket=bucket)
        logger.info("S3 bucket '%s' already exists.", bucket)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket)
            logger.info("S3 bucket '%s' created.", bucket)
        else:
            raise

    # Apply a public-read policy so uploaded objects are accessible.
    # This replaces the deprecated ACL="public-read" approach which is no
    # longer supported by MinIO RELEASE.2022-10-29+.
    public_read_policy = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                }
            ],
        }
    )
    try:
        client.put_bucket_policy(Bucket=bucket, Policy=public_read_policy)
        logger.info("Public-read policy applied to bucket '%s'.", bucket)
    except ClientError as exc:
        logger.warning("Could not apply bucket policy to '%s': %s", bucket, exc)


def upload_file(
    file_bytes: bytes,
    original_filename: str,
    content_type: str = "application/octet-stream",
) -> Tuple[str, str]:
    """Upload a file to S3 object storage and return (object_key, object_key).

    Args:
        file_bytes: Raw bytes of the file to upload.
        original_filename: The original client-side filename (used to derive extension).
        content_type: MIME type of the file.

    Returns:
        A tuple of (object_key, object_key).
        - object_key: The key stored in S3 (e.g. "uploads/<uuid>.pdf").
        - The second element is the same object key, returned for caller convenience.
    """
    ensure_bucket_exists()

    ext = ""
    if "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()

    object_key = f"uploads/{uuid.uuid4()}{ext}"

    client = _get_s3_client()
    
    hasher = hashlib.sha256()
    hasher.update(file_bytes)
    local_sha256 = hasher.hexdigest()

    client.put_object(
        Bucket=settings.S3_BUCKET,
        Key=object_key,
        Body=file_bytes,
        ContentType=content_type,
        ChecksumAlgorithm='SHA256',
        ChecksumSHA256=local_sha256
        # Public read is granted via bucket policy set in ensure_bucket_exists().
        # ACL="public-read" is not used: MinIO 2022+ disables S3 ACLs by default.
    )

    logger.info("Uploaded '%s' as key '%s'", original_filename, object_key)
    return object_key, object_key


def get_presigned_url(object_key: str, expiration: int = 3600) -> str:
    """Generate a pre-signed URL for temporary access to an S3 object.

    Args:
        object_key: The S3 object key.
        expiration: URL validity in seconds (default 1 hour).

    Returns:
        Pre-signed URL string.
    """
    client = _get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": object_key},
        ExpiresIn=expiration,
    )


def delete_file(object_key: str) -> bool:
    """Delete a file from S3 object storage.

    Args:
        object_key: The S3 object key to delete.

    Returns:
        True if deleted successfully, False otherwise.
    """
    try:
        client = _get_s3_client()
        client.delete_object(Bucket=settings.S3_BUCKET, Key=object_key)
        return True
    except ClientError as exc:
        logger.warning("Failed to delete S3 object '%s': %s", object_key, exc)
        return False


def get_object_size(object_key: str) -> int:
    """Return the byte-size of an S3 object via a HEAD request.

    No object data is transferred.  Returns 0 when the object cannot be
    found or the call fails so that callers can still persist a FormVersion
    row with a placeholder size without blocking a publish transition.

    Args:
        object_key: The S3 object key to interrogate.

    Returns:
        Content length in bytes, or 0 on any failure.
    """
    try:
        client = _get_s3_client()
        response = client.head_object(Bucket=settings.S3_BUCKET, Key=object_key)
        return int(response.get("ContentLength", 0))
    except ClientError as exc:
        logger.warning("Could not get size for S3 object '%s': %s", object_key, exc)
        return 0


# ─── Streaming download (admin-side) ──────────────────────────────────────────

# Per-chunk size used by ``stream_object``.  64 KiB is large enough to keep
# Python-loop overhead negligible on multi-MB files while small enough to keep
# the worker's resident-set memory bounded under high concurrency.  Public
# because the unit test asserts the chunking contract.
STREAM_CHUNK_SIZE: int = 64 * 1024


def stream_object(
    object_key: str,
    chunk_size: int = STREAM_CHUNK_SIZE,
) -> Iterator[bytes]:
    """Stream an S3 object's bytes in bounded chunks.

    This helper exists so the admin backend can deliver attachment downloads
    **without ever exposing the S3 endpoint / bucket / object key / signed URL
    to the client browser** (FEAT-0005 US-004 AC14, US-012 BR-001).  The
    caller — typically a FastAPI route — wraps the returned iterator in a
    ``StreamingResponse`` together with ``Content-Disposition`` and
    ``Cache-Control`` headers.

    Args:
        object_key: S3 object key to read.  Server-derived only; never
            constructed from client input.
        chunk_size: Bytes per yielded chunk.  Defaults to 64 KiB; values
            outside the range 1..1 MiB are clamped.

    Yields:
        Successive ``bytes`` chunks from the S3 object body.

    Raises:
        S3ObjectNotFound: If the object does not exist (``NoSuchKey``).  The
            exception message does not contain the requested key.
        ClientError: For any other S3/client error.

    Security notes:
        * The boto3 streaming body is closed when iteration ends or the
          generator is garbage collected — preventing leaked HTTPS sockets.
        * No exception path includes the ``object_key`` in its message so
          stack traces / 5xx bodies cannot leak the storage layout.
        * Callers MUST NOT pass the iterator value back to clients verbatim
          as JSON; the bytes are the file payload, not metadata.
    """
    # Clamp chunk_size to a sensible bound (defensive — protects callers
    # from accidentally passing 0 or megabyte values).
    if chunk_size <= 0:
        chunk_size = STREAM_CHUNK_SIZE
    chunk_size = min(chunk_size, 1024 * 1024)

    client = _get_s3_client()
    try:
        response = client.get_object(Bucket=settings.S3_BUCKET, Key=object_key)
    except ClientError as exc:
        code = (exc.response or {}).get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            # Do NOT include object_key in the message.
            logger.info("S3 stream_object: object not found")
            raise S3ObjectNotFound("S3 object not found") from None
        # Generic S3/network failure — log without the key.
        logger.warning("S3 stream_object failed: code=%s", code or "unknown")
        raise

    body = response["Body"]
    try:
        # ``iter_chunks`` yields ``bytes`` objects of at most ``chunk_size``
        # — the canonical streaming pattern for botocore ``StreamingBody``.
        for chunk in body.iter_chunks(chunk_size=chunk_size):
            if chunk:
                yield chunk
    finally:
        # Ensure the underlying HTTPS connection is released even when the
        # client aborts mid-download.
        try:
            body.close()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass
