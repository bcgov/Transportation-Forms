import pytest


def test_list_business_areas_admin(client, admin_token_headers):
    response = client.get(
        "/api/v1/admin/business-areas",
        headers=admin_token_headers,
    )
    assert response.status_code == 200
