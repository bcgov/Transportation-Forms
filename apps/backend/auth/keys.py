"""RSA key management for JWT token signing and verification."""

from collections.abc import Mapping
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


JWT_PRIVATE_KEY_ENV = "JWT_PRIVATE_KEY_PEM"
JWT_PUBLIC_KEY_ENV = "JWT_PUBLIC_KEY_PEM"


class JWTKeyConfigurationError(RuntimeError):
    """Raised when required JWT key material is missing or invalid."""


def _required_pem(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        raise JWTKeyConfigurationError(
            f"Missing required security configuration: {name}"
        )
    return value.replace("\\n", "\n").strip()


def load_jwt_key_pair_from_env(
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Load and validate the configured application JWT RSA key pair."""
    source = os.environ if env is None else env
    private_pem = _required_pem(source, JWT_PRIVATE_KEY_ENV)
    public_pem = _required_pem(source, JWT_PUBLIC_KEY_ENV)

    try:
        private_key = serialization.load_pem_private_key(
            private_pem.encode("utf-8"),
            password=None,
        )
        public_key = serialization.load_pem_public_key(public_pem.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise JWTKeyConfigurationError(
            "Invalid JWT PEM key configuration: keys must be valid RSA PEM values"
        ) from exc

    if not isinstance(private_key, rsa.RSAPrivateKey) or not isinstance(
        public_key, rsa.RSAPublicKey
    ):
        raise JWTKeyConfigurationError(
            "Invalid JWT PEM key configuration: keys must be RSA keys"
        )

    if private_key.public_key().public_numbers() != public_key.public_numbers():
        raise JWTKeyConfigurationError(
            "Invalid JWT PEM key configuration: public key does not match private key"
        )

    return private_pem, public_pem


PRIVATE_KEY, PUBLIC_KEY = load_jwt_key_pair_from_env()
