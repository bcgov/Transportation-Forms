"""Live S3 credential validation test.

Connects to the real S3 endpoint configured in the root .env file and verifies:
  1. The bucket is reachable (credentials are valid)
  2. A small object can be uploaded (PUT permission works)
  3. The same object can be downloaded and compared (GET permission works)
  4. The object can be deleted (DELETE permission works)

This test is intentionally NOT mocked.  Its sole purpose is to validate that
the S3_* variables in .env point to a working, accessible service.

Run with:
    pytest tests/test_s3_credentials_live.py -v -s

Mark: s3_live  (skip in normal CI with:  pytest -m "not s3_live")
"""

import base64
import uuid
import hashlib
import pytest
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointResolutionError, NoCredentialsError

from backend.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_settings():
    """Return a new Settings() instance that re-reads .env from disk.

    The module-level ``settings`` singleton in backend.config is frozen at
    import time.  Calling Settings() directly forces pydantic-settings to
    re-read the .env file on every invocation, so changes made after the
    process started are always picked up.
    """
    return Settings()  # type: ignore[call-arg]


def _make_client():
    """Create a boto3 S3 client using credentials read fresh from .env."""
    s = _fresh_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.S3_ENDPOINT_URL,
        aws_access_key_id=s.S3_ACCESS_KEY,
        aws_secret_access_key=s.S3_SECRET_KEY,
        verify=s.S3_VERIFY_TLS,
        config=Config(signature_version="s3v4"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.s3_live
class TestS3LiveCredentials:
    """Full round-trip test against the real S3 endpoint from .env."""

    # Unique key so parallel test runs never collide
    OBJECT_KEY = f"_s3_credential_check/{uuid.uuid4().hex}.txt"
    PAYLOAD = b"s3-credential-check-probe"

    def test_01_settings_are_populated(self):
        """Fail fast if any required S3 setting is missing or empty."""
        s = _fresh_settings()
        missing = [
            name
            for name, value in {
                "S3_ENDPOINT_URL": s.S3_ENDPOINT_URL,
                "S3_ACCESS_KEY": s.S3_ACCESS_KEY,
                "S3_SECRET_KEY": s.S3_SECRET_KEY,
                "S3_BUCKET": s.S3_BUCKET,
            }.items()
            if not value
        ]
        assert not missing, (
            f"Missing S3 settings in .env: {', '.join(missing)}\n"
            "Populate these before running the live credential test."
        )

    def test_02_bucket_is_reachable(self):
        """Verify the configured bucket exists and credentials can list it."""
        s = _fresh_settings()
        client = _make_client()
        try:
            client.head_bucket(Bucket=s.S3_BUCKET)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            pytest.fail(
                f"head_bucket failed with [{code}].\n"
                f"  endpoint : {s.S3_ENDPOINT_URL}\n"
                f"  bucket   : {s.S3_BUCKET}\n"
                f"  Possible causes: wrong endpoint, wrong bucket name, "
                f"or invalid credentials."
            )

    def test_03_upload_succeeds(self):
        """Upload a small probe object to the bucket."""
        s = _fresh_settings()
        client = _make_client()
        
        checksum_sha256 = base64.b64encode(
            hashlib.sha256(self.PAYLOAD).digest()
        ).decode("ascii")

        try:
            client.put_object(
                Bucket=s.S3_BUCKET,
                Key=self.OBJECT_KEY,
                Body=self.PAYLOAD,
                ContentType="text/plain",
                ChecksumAlgorithm="SHA256",
                ChecksumSHA256=checksum_sha256,
            )
        except (ClientError, NoCredentialsError, EndpointResolutionError) as exc:
            pytest.fail(
                f"put_object failed: {exc}\n"
                f"  endpoint : {s.S3_ENDPOINT_URL}\n"
                f"  bucket   : {s.S3_BUCKET}\n"
                f"  key      : {self.OBJECT_KEY}\n"
                "Check that S3_ACCESS_KEY / S3_SECRET_KEY are correct and "
                "have write permission on this bucket."
            )

  
    def test_04_download_matches_upload(self):
        """Download the probe object and verify its content matches what was uploaded."""
        s = _fresh_settings()
        client = _make_client()
        try:
            response = client.get_object(
                Bucket=s.S3_BUCKET,
                Key=self.OBJECT_KEY,
            )
            body = response["Body"].read()
        except ClientError as exc:
            pytest.fail(
                f"get_object failed: {exc}\n"
                "Upload may have succeeded but download failed — "
                "check GET permissions on the bucket."
            )
        assert body == self.PAYLOAD, (
            f"Downloaded content does not match uploaded content.\n"
            f"  expected : {self.PAYLOAD!r}\n"
            f"  got      : {body!r}"
        )

    def test_05_delete_succeeds(self):
        """Delete the probe object (cleanup) and confirm it is gone."""
        s = _fresh_settings()
        client = _make_client()
        try:
            client.delete_object(
                Bucket=s.S3_BUCKET,
                Key=self.OBJECT_KEY,
            )
        except ClientError as exc:
            pytest.fail(
                f"delete_object failed: {exc}\n"
                "Check that S3_ACCESS_KEY has DELETE permission on this bucket."
            )

        # Confirm deletion
        try:
            client.head_object(Bucket=s.S3_BUCKET, Key=self.OBJECT_KEY)
            pytest.fail("Object still exists after delete — deletion did not work.")
        except ClientError as exc:
            assert exc.response["Error"]["Code"] in ("404", "NoSuchKey"), (
                f"Unexpected error checking deletion: {exc}"
            )
