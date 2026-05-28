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
from typing import Tuple

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
