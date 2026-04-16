from cryptography.fernet import Fernet

from app.core.config import get_settings


def _get_fernet() -> Fernet:
    return Fernet(get_settings().fernet_key.encode())


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
