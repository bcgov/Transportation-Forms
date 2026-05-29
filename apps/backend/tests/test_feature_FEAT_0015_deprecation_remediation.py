"""FEAT-0015 regression coverage for backend framework deprecation remediation."""

from pathlib import Path
import warnings

from pydantic.warnings import PydanticDeprecatedSince20
from sqlalchemy.exc import MovedIn20Warning
from sqlalchemy.orm import DeclarativeBase

from backend.config import Settings
from backend.database import Base


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_targeted_backend_deprecated_patterns_are_removed():
    """Owner code should not reintroduce the migrated framework patterns."""
    targets = {
        BACKEND_DIR / "config.py": ("class Config:",),
        BACKEND_DIR / "database.py": (
            "sqlalchemy.ext.declarative",
            "declarative_base(",
        ),
        BACKEND_DIR / "main.py": ("on_event(",),
        BACKEND_DIR / "routes" / "forms.py": ("class Config:",),
        BACKEND_DIR / "routes" / "business_areas.py": ("class Config:",),
        BACKEND_DIR / "routes" / "prefixes.py": ("class Config:",),
        BACKEND_DIR / "routes" / "reservations.py": ("class Config:",),
    }

    remaining = []
    for path, patterns in targets.items():
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern in text:
                remaining.append(f"{path.relative_to(BACKEND_DIR.parent)}: {pattern}")

    assert not remaining


def test_backend_settings_config_behavior_is_preserved():
    model_config = Settings.model_config

    assert model_config["env_file"] == ".env"
    assert model_config["case_sensitive"] is True
    assert model_config["extra"] == "ignore"
    assert Settings.model_fields["S3_VERIFY_TLS"].default is True


def test_backend_sqlalchemy_base_uses_modern_declarative_base():
    assert issubclass(Base, DeclarativeBase)


def test_backend_warning_gates_are_registered():
    expected_categories = {
        PydanticDeprecatedSince20,
        MovedIn20Warning,
        DeprecationWarning,
    }
    configured_categories = {
        warning_filter[2]
        for warning_filter in warnings.filters
        if warning_filter[0] == "error"
    }

    assert expected_categories.issubset(configured_categories)
