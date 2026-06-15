import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError
from backend.services.s3_service import (
    ensure_bucket_exists, 
    upload_file, 
    get_presigned_url, 
    delete_file,
    get_object_size,
    stream_object,
    S3ObjectNotFound
)

class TestS3Service:
    @patch("backend.services.s3_service._get_s3_client")
    def test_ensure_bucket_creates_bucket_if_missing(self, mock_get_client):
        mock_client = mock_get_client.return_value
        # Define that the bucket doesn't exist
        mock_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, 
            "HeadBucket"
        )
        
        ensure_bucket_exists()
        mock_client.create_bucket.assert_called_once()  # bucket name comes from settings

    @patch("backend.services.s3_service._get_s3_client")
    def test_upload_file_success(self, mock_get_client):
        mock_client = mock_get_client.return_value
        result = upload_file(b"content", "test.pdf")
        mock_client.put_object.assert_called_once()
        object_key, public_url = result
        assert object_key.startswith("uploads/") and object_key.endswith(".pdf")

    @patch("backend.services.s3_service._get_s3_client")
    def test_get_presigned_url(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.generate_presigned_url.return_value = "http://signed.url"
        
        url = get_presigned_url("test.pdf")
        assert url == "http://signed.url"
        mock_client.generate_presigned_url.assert_called_once()

    @patch("backend.services.s3_service._get_s3_client")
    def test_delete_file(self, mock_get_client):
        mock_client = mock_get_client.return_value
        delete_file("test.pdf")
        mock_client.delete_object.assert_called_once()

    @patch("backend.services.s3_service._get_s3_client")
    def test_upload_raises_on_boto_error(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.put_object.side_effect = ClientError(
             {"Error": {"Code": "500", "Message": "Internal Error"}}, 
             "PutObject"
        )
        
        with pytest.raises(Exception, match="Internal Error"):
            upload_file(b"data", "test.pdf")

    @patch("backend.services.s3_service._get_s3_client")
    def test_get_object_size_success(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.head_object.return_value = {"ContentLength": 1234}
        
        size = get_object_size("test.pdf")
        assert size == 1234
        mock_client.head_object.assert_called_once()
        assert mock_client.head_object.call_args[1]["Key"] == "test.pdf"

    @patch("backend.services.s3_service._get_s3_client")
    def test_get_object_size_failure(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.head_object.side_effect = ClientError(
             {"Error": {"Code": "404", "Message": "Not Found"}}, 
             "HeadObject"
        )
        
        size = get_object_size("nonexistent.pdf")
        assert size == 0

    @patch("backend.services.s3_service._get_s3_client")
    def test_stream_object_success_and_closure(self, mock_get_client):
        mock_client = mock_get_client.return_value
        
        mock_body = MagicMock()
        mock_body.iter_chunks.return_value = [b"chunk1", b"chunk2"]
        mock_client.get_object.return_value = {"Body": mock_body}
        
        chunks = list(stream_object("test.pdf", chunk_size=1024))
        
        assert chunks == [b"chunk1", b"chunk2"]
        mock_client.get_object.assert_called_once()
        assert mock_client.get_object.call_args[1]["Key"] == "test.pdf"
        mock_body.iter_chunks.assert_called_once_with(chunk_size=1024)
        mock_body.close.assert_called_once()

    @patch("backend.services.s3_service._get_s3_client")
    def test_stream_object_chunk_clamping(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_body = MagicMock()
        mock_body.iter_chunks.return_value = []
        mock_client.get_object.return_value = {"Body": mock_body}
        
        # Test lower bound (<= 0 clamps to STREAM_CHUNK_SIZE, which is 65536)
        list(stream_object("test.pdf", chunk_size=0))
        mock_body.iter_chunks.assert_called_with(chunk_size=65536)
        
        # Test upper bound (> 1048576 clamps to 1048576)
        list(stream_object("test.pdf", chunk_size=2000000))
        mock_body.iter_chunks.assert_called_with(chunk_size=1048576)

    @patch("backend.services.s3_service._get_s3_client")
    def test_stream_object_not_found(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.get_object.side_effect = ClientError(
             {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}}, 
             "GetObject"
        )
        
        with pytest.raises(S3ObjectNotFound, match="S3 object not found"):
            list(stream_object("missing.pdf"))

    @patch("backend.services.s3_service._get_s3_client")
    def test_stream_object_other_error(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.get_object.side_effect = ClientError(
             {"Error": {"Code": "InternalError", "Message": "Something went wrong"}}, 
             "GetObject"
        )
        
        with pytest.raises(ClientError):
            list(stream_object("test.pdf"))
