import uuid
import pytest
from fastapi import status

@pytest.mark.integration
class TestPrefixesApi:
    def test_list_active_prefixes_public(self, client, db, user_token_headers):
        response = client.get("/api/v1/prefixes", headers=user_token_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        
    def test_admin_list_prefixes(self, client, admin_token_headers):
        response = client.get("/api/v1/admin/prefixes", headers=admin_token_headers)
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.json(), list)

    def test_non_admin_cannot_access_admin_prefixes(self, client, user_token_headers):
        response = client.get("/api/v1/admin/prefixes", headers=user_token_headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_create_prefix(self, client, admin_token_headers):
        payload = {
            "prefix": "TSTPFX",
            "description": "Test Prefix",
            "padding_length": 4,
            "max_number_length": 10,
            "is_case_sensitive": False
        }
        response = client.post("/api/v1/admin/prefixes", json=payload, headers=admin_token_headers)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["prefix"] == "TSTPFX"
        assert data["description"] == "Test Prefix"

    def test_admin_create_duplicate_prefix_fails(self, client, admin_token_headers):
        payload = {
            "prefix": "DUPPFX",
            "description": "Duplicate Prefix",
            "padding_length": 4,
            "max_number_length": 10,
            "is_case_sensitive": False
        }
        # First creation
        client.post("/api/v1/admin/prefixes", json=payload, headers=admin_token_headers)
        
        # Second creation should fail
        response = client.post("/api/v1/admin/prefixes", json=payload, headers=admin_token_headers)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_admin_get_prefix(self, client, admin_token_headers):
        # Create one first
        payload = {"prefix": "GETPFX", "padding_length": 4, "max_number_length": 10}
        create_resp = client.post("/api/v1/admin/prefixes", json=payload, headers=admin_token_headers)
        prefix_id = create_resp.json()["id"]

        # Get by ID
        response = client.get(f"/api/v1/admin/prefixes/{prefix_id}", headers=admin_token_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["prefix"] == "GETPFX"

    def test_admin_get_nonexistent_prefix_fails(self, client, admin_token_headers):
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/admin/prefixes/{fake_id}", headers=admin_token_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_admin_update_prefix(self, client, admin_token_headers):
        payload = {"prefix": "UPDPFX", "padding_length": 4, "max_number_length": 10}
        create_resp = client.post("/api/v1/admin/prefixes", json=payload, headers=admin_token_headers)
        prefix_id = create_resp.json()["id"]

        update_payload = {
            "description": "Updated Description",
            "is_active": False,
            "padding_length": 5
        }
        update_resp = client.put(f"/api/v1/admin/prefixes/{prefix_id}", json=update_payload, headers=admin_token_headers)
        assert update_resp.status_code == status.HTTP_200_OK
        data = update_resp.json()
        assert data["description"] == "Updated Description"
        assert data["is_active"] is False

    def test_admin_delete_prefix(self, client, admin_token_headers):
        payload = {"prefix": "DELPFX", "padding_length": 4, "max_number_length": 10}
        create_resp = client.post("/api/v1/admin/prefixes", json=payload, headers=admin_token_headers)
        prefix_id = create_resp.json()["id"]

        # Delete it
        del_resp = client.delete(f"/api/v1/admin/prefixes/{prefix_id}", headers=admin_token_headers)
        assert del_resp.status_code == status.HTTP_200_OK

        # Fetching it should now 404
        get_resp = client.get(f"/api/v1/admin/prefixes/{prefix_id}", headers=admin_token_headers)
        assert get_resp.status_code == status.HTTP_404_NOT_FOUND

    def test_invalid_prefix_payload_rejected(self, client, admin_token_headers):
        payload = {
            "prefix": "INVALID-PREFIX!!!",
            "padding_length": 4,
            "max_number_length": 10
        }
        response = client.post("/api/v1/admin/prefixes", json=payload, headers=admin_token_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
