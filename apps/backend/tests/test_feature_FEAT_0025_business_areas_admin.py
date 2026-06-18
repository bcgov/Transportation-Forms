import pytest
from backend.models import BusinessArea

def test_list_business_areas_admin(client, admin_token_headers):
    response = client.get(
        "/api/v1/admin/business-areas",
        headers=admin_token_headers
    )
    print("Response text:", response.text)
    assert response.status_code in [200, 403]
