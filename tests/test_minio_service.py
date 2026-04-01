import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError
from backend.services.minio_service import ensure_bucket_exists, upload_file, get_presigned_url, delete_file

class TestMinioService:
    @patch("backend.services.minio_service._get_s3_client")
    def test_ensure_bucket_creates_bucket_if_missing(self, mock_get_client):
        mock_client = mock_get_client.return_value
        # Define that the bucket doesn't exist
        mock_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, 
            "HeadBucket"
        )
        
        ensure_bucket_exists()
        mock_client.create_bucket.assert_called_once_with(Bucket="transportation-forms") # assuming default env bucket

    @patch("backend.services.minio_service._get_s3_client")
    def test_upload_file_success(self, mock_get_client):
        mock_client = mock_get_client.return_value
        result = upload_file(b"content", "test.pdf")
        mock_client.put_object.assert_called_once()
        assert result == "test.pdf"

    @patch("backend.services.minio_service._get_s3_client")
    def test_get_presigned_url(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.generate_presigned_url.return_value = "http://signed.url"
        
        url = get_presigned_url("test.pdf")
        assert url == "http://signed.url"
        mock_client.generate_presigned_url.assert_called_once()

    @patch("backend.services.minio_service._get_s3_client")
    def test_delete_file(self, mock_get_client):
        mock_client = mock_get_client.return_value
        delete_file("test.pdf")
        mock_client.delete_object.assert_called_once()

    @patch("backend.services.minio_service._get_s3_client")
    def test_upload_raises_on_boto_error(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.put_object.side_effect = ClientError(
             {"Error": {"Code": "500", "Message": "Internal Error"}}, 
             "PutObject"
        )
        
        with pytest.raises(Exception, match="Internal Error"):
            upload_file(b"data", "test.pdf")
