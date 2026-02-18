"""
Test python-keycloak with detailed HTTP logging to see exact requests.
"""

import logging
import http.client as http_client
from keycloak import KeycloakOpenID
from backend.config import settings

# Enable HTTP debugging
http_client.HTTPConnection.debuglevel = 1

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

print("=" * 80)
print("Testing with HTTP Debug Logging")
print("=" * 80)
print()
print(f"Server URL: {settings.KEYCLOAK_SERVER_URL}")
print(f"Realm: {settings.KEYCLOAK_REALM}")
print()
print("Making request...")
print("-" * 80)

try:
    client = KeycloakOpenID(
        server_url=settings.KEYCLOAK_SERVER_URL,
        realm_name=settings.KEYCLOAK_REALM,
        client_id=settings.KEYCLOAK_CLIENT_ID,
        client_secret_key=settings.KEYCLOAK_CLIENT_SECRET
    )
    
    well_known = client.well_known()
    print("-" * 80)
    print()
    print("SUCCESS!")
    print(f"Issuer: {well_known.get('issuer')}")
    
except Exception as e:
    print("-" * 80)
    print()
    print(f"FAILED: {str(e)}")

print()
print("=" * 80)
