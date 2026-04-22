from typing import Optional

from cryptography.fernet import Fernet

_fernet_instance: Optional[Fernet] = None


def init_fernet(key: str) -> None:
    """Initialize the Fernet instance with the given key. Called at app startup."""
    global _fernet_instance
    _fernet_instance = Fernet(key.encode())


def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        from app.core.config import get_settings
        init_fernet(get_settings().fernet_key)
    assert _fernet_instance is not None
    return _fernet_instance


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token for storage. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stored token. Returns plaintext."""
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def reset_fernet() -> None:
    """Reset the Fernet instance. Used in tests."""
    global _fernet_instance
    _fernet_instance = None
