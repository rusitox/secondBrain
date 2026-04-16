"""Unit tests for token encryption/decryption."""
import pytest
from cryptography.fernet import Fernet

from app.utils.encryption import (
    decrypt_token,
    encrypt_token,
    init_fernet,
    reset_fernet,
)


@pytest.fixture(autouse=True)
def setup_fernet() -> None:
    """Ensure Fernet is initialized with a test key for each test."""
    reset_fernet()
    init_fernet(Fernet.generate_key().decode())


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self) -> None:
        original = "xoxb-slack-token-12345"
        encrypted = encrypt_token(original)
        assert encrypted != original
        assert decrypt_token(encrypted) == original

    def test_encrypt_empty_string(self) -> None:
        assert encrypt_token("") == ""

    def test_decrypt_empty_string(self) -> None:
        assert decrypt_token("") == ""

    def test_encrypted_value_is_different_each_time(self) -> None:
        """Fernet uses a timestamp + IV, so same plaintext produces different ciphertext."""
        token = "my-secret-token"
        enc1 = encrypt_token(token)
        enc2 = encrypt_token(token)
        assert enc1 != enc2
        assert decrypt_token(enc1) == token
        assert decrypt_token(enc2) == token

    def test_decrypt_invalid_ciphertext(self) -> None:
        with pytest.raises(Exception):
            decrypt_token("not-valid-ciphertext")
