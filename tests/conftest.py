"""Pytest configuration and fixtures."""

import pytest
import os
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
if str(project_root) not in os.sys.path:
    os.sys.path.insert(0, str(project_root))


@pytest.fixture
def test_user_id():
    """Fixture providing a test user ID."""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def test_user_data():
    """Fixture providing test user data."""
    return {
        "user_id": "550e8400-e29b-41d4-a716-446655440000",
        "email": "test@example.com",
        "name": "Test User",
        "roles": ["admin", "staff_manager"]
    }


@pytest.fixture
def test_roles():
    """Fixture providing test roles."""
    return {
        "admin": {"name": "admin", "permissions": ["*"]},
        "staff_manager": {"name": "staff_manager", "permissions": ["forms:create", "forms:edit", "forms:publish"]},
        "reviewer": {"name": "reviewer", "permissions": ["forms:review", "forms:approve"]},
        "staff_viewer": {"name": "staff_viewer", "permissions": ["forms:view"]}
    }
