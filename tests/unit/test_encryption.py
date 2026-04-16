"""Unit tests for token encryption/decryption."""
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from app.utils.encryption import decrypt_token, encrypt_token


# Generate a real Fernet key for testing
TEST_FERNET_KEY = Fernet.generate_key().decode()


class FakeSettings:
    fernet_key = TEST_FERNET_KEY


@patch("app.utils.encryption.get_settings", return_value=FakeSettings())
class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self, mock_settings) -> None:
        original = "xoxb-slack-token-12345"
        encrypted = encrypt_token(original)
        assert encrypted != original
        assert decrypt_token(encrypted) == original

    def test_encrypt_empty_string(self, mock_settings) -> None:
        assert encrypt_token("") == ""

    def test_decrypt_empty_string(self, mock_settings) -> None:
        assert decrypt_token("") == ""

    def test_encrypted_value_is_different_each_time(self, mock_settings) -> None:
        """Fernet uses a timestamp + IV, so same plaintext produces different ciphertext."""
        token = "my-secret-token"
        enc1 = encrypt_token(token)
        enc2 = encrypt_token(token)
        assert enc1 != enc2
        # But both decrypt to the same value
        assert decrypt_token(enc1) == token
        assert decrypt_token(enc2) == token

    def test_decrypt_invalid_ciphertext(self, mock_settings) -> None:
        with pytest.raises(Exception):
            decrypt_token("not-valid-ciphertext")
