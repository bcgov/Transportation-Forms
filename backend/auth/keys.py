"""RSA key management for JWT token signing and verification."""

import os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend


def get_keys_directory() -> Path:
    """Get or create the keys directory."""
    keys_dir = Path(__file__).parent / "keys"
    keys_dir.mkdir(exist_ok=True)
    return keys_dir


def get_private_key_path() -> Path:
    """Get the path to the private key file."""
    return get_keys_directory() / "private_key.pem"


def get_public_key_path() -> Path:
    """Get the path to the public key file."""
    return get_keys_directory() / "public_key.pem"


def generate_rsa_keys() -> tuple:
    """
    Generate RSA 2048-bit key pair for JWT signing.
    
    Returns:
        tuple: (private_key_str, public_key_str)
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

    return private_pem, public_pem


def ensure_keys_exist() -> tuple:
    """
    Ensure RSA keys exist. Generate them if not present.
    
    Returns:
        tuple: (private_key_str, public_key_str)
    """
    private_key_path = get_private_key_path()
    public_key_path = get_public_key_path()

    # Generate keys if they don't exist
    if not private_key_path.exists() or not public_key_path.exists():
        private_pem, public_pem = generate_rsa_keys()
        
        private_key_path.write_text(private_pem, encoding='utf-8')
        public_key_path.write_text(public_pem, encoding='utf-8')
        
        # Restrict permissions on private key (Unix-like systems)
        try:
            os.chmod(private_key_path, 0o600)
        except (AttributeError, OSError):
            # Windows doesn't support chmod in the same way
            pass

    private_pem = private_key_path.read_text(encoding='utf-8')
    public_pem = public_key_path.read_text(encoding='utf-8')

    return private_pem, public_pem


# Load keys on module import
PRIVATE_KEY, PUBLIC_KEY = ensure_keys_exist()
