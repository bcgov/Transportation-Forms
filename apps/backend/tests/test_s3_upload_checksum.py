import base64
import hashlib
from unittest.mock import MagicMock, patch

from backend.services.s3_service import upload_file


def test_upload_file_passes_base64_sha256_checksum_to_put_object():
    payload = b"deterministic checksum payload"
    mock_client = MagicMock()

    with (
        patch("backend.services.s3_service.ensure_bucket_exists"),
        patch(
            "backend.services.s3_service._get_s3_client",
            return_value=mock_client,
        ),
    ):
        upload_file(payload, "test.pdf", "application/pdf")

    mock_client.put_object.assert_called_once()
    put_arguments = mock_client.put_object.call_args.kwargs

    assert put_arguments["ChecksumAlgorithm"] == "SHA256"
    assert (
        base64.b64decode(put_arguments["ChecksumSHA256"], validate=True)
        == hashlib.sha256(payload).digest()
    )
