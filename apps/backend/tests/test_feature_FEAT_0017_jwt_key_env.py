"""FEAT-0017 coverage for environment-backed JWT signing keys."""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.auth.keys import (
    JWTKeyConfigurationError,
    load_jwt_key_pair_from_env,
)


BACKEND_AUTH_DIR = Path(__file__).resolve().parents[1] / "auth"


def _generate_test_pair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def test_valid_jwt_pem_env_pair_loads_successfully():
    private_pem, public_pem = _generate_test_pair()

    loaded_private, loaded_public = load_jwt_key_pair_from_env(
        {
            "JWT_PRIVATE_KEY_PEM": private_pem,
            "JWT_PUBLIC_KEY_PEM": public_pem,
        }
    )

    assert loaded_private == private_pem.strip()
    assert loaded_public == public_pem.strip()


def test_missing_private_key_env_fails_with_non_secret_message():
    _, public_pem = _generate_test_pair()

    with pytest.raises(JWTKeyConfigurationError) as exc_info:
        load_jwt_key_pair_from_env({"JWT_PUBLIC_KEY_PEM": public_pem})

    assert "JWT_PRIVATE_KEY_PEM" in str(exc_info.value)
    assert "BEGIN" not in str(exc_info.value)


def test_missing_public_key_env_fails_with_non_secret_message():
    private_pem, _ = _generate_test_pair()

    with pytest.raises(JWTKeyConfigurationError) as exc_info:
        load_jwt_key_pair_from_env({"JWT_PRIVATE_KEY_PEM": private_pem})

    assert "JWT_PUBLIC_KEY_PEM" in str(exc_info.value)
    assert "BEGIN" not in str(exc_info.value)


def test_invalid_or_mismatched_jwt_pem_env_fails_without_logging_key_material():
    private_pem, _ = _generate_test_pair()
    _, mismatched_public_pem = _generate_test_pair()

    with pytest.raises(JWTKeyConfigurationError) as exc_info:
        load_jwt_key_pair_from_env(
            {
                "JWT_PRIVATE_KEY_PEM": private_pem,
                "JWT_PUBLIC_KEY_PEM": mismatched_public_pem,
            }
        )

    error = str(exc_info.value)
    assert "public key does not match private key" in error
    assert "BEGIN" not in error
    assert private_pem not in error
    assert mismatched_public_pem not in error


def test_jwt_key_loader_has_no_file_fallback_or_generation_path():
    source = (BACKEND_AUTH_DIR / "keys.py").read_text(encoding="utf-8")

    assert "generate_private_key" not in source
    assert "write_text" not in source
    assert "read_text" not in source
    assert "private_key.pem" not in source
    assert "public_key.pem" not in source