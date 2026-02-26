"""MinIO file storage service (S3-compatible).

Provides file upload/delete operations backed by MinIO for local development
and S3-compatible object stores for production.

Uses boto3 (already in requirements.txt) with an endpoint_url override so the
same code works with both MinIO and real AWS S3.
"""

import io
import uuid
import logging
import os
from typing import Tuple, Optional

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from backend.config import settings

logger = logging.getLogger(__name__)


def _get_s3_client():
    """Return a boto3 S3 client pointed at MinIO (or real S3 in production)."""
    return boto3.client(
        "s3",
        endpoint_url=settings.MINIO_ENDPOINT,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",  # MinIO ignores region but boto3 requires one
    )


def ensure_bucket_exists() -> None:
    """Create the configured bucket if it does not already exist."""
    client = _get_s3_client()
    bucket = settings.MINIO_BUCKET
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket)
            logger.info("MinIO bucket '%s' created.", bucket)
        else:
            # Re-raise unexpected errors
            raise


def upload_file(
    file_bytes: bytes,
    original_filename: str,
    content_type: str = "application/octet-stream",
) -> Tuple[str, str]:
    """Upload a file to MinIO and return (object_key, public_url).

    Args:
        file_bytes: Raw bytes of the file to upload.
        original_filename: The original client-side filename (used to derive extension).
        content_type: MIME type of the file.

    Returns:
        A tuple of (object_key, public_url).
        - object_key: The key stored in MinIO (e.g. "uploads/<uuid>.pdf").
        - public_url: Publicly accessible URL for the file.
    """
    ensure_bucket_exists()

    ext = ""
    if "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()

    object_key = f"uploads/{uuid.uuid4()}{ext}"

    client = _get_s3_client()
    client.put_object(
        Bucket=settings.MINIO_BUCKET,
        Key=object_key,
        Body=file_bytes,
        ContentType=content_type,
        # Make the object publicly readable so browsers can directly access it
        ACL="public-read",
    )

    public_url = f"{settings.MINIO_PUBLIC_URL}/{settings.MINIO_BUCKET}/{object_key}"
    logger.info("Uploaded '%s' → %s", original_filename, public_url)
    return object_key, public_url


def delete_file(object_key: str) -> bool:
    """Delete a file from MinIO.

    Args:
        object_key: The MinIO object key to delete.

    Returns:
        True if deleted successfully, False otherwise.
    """
    try:
        client = _get_s3_client()
        client.delete_object(Bucket=settings.MINIO_BUCKET, Key=object_key)
        return True
    except ClientError as exc:
        logger.warning("Failed to delete MinIO object '%s': %s", object_key, exc)
        return False
