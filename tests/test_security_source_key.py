"""Tests for backend.security.source_key."""

import os
import stat

import pytest

from backend.config import settings
from backend.security import source_key


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Every test runs with a fresh data dir and no inherited env secret."""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.delenv("CONFIG_SECRET", raising=False)
    source_key._reset_cache_for_tests()
    yield
    source_key._reset_cache_for_tests()


def test_pbkdf2_path(monkeypatch, tmp_path):
    """CONFIG_SECRET env produces a deterministic key; labels source correctly."""
    monkeypatch.setenv("CONFIG_SECRET", "hunter2-very-secret")

    token = source_key.encrypt_pat("ghp_abc123")

    # Cache reset: with the same secret, a fresh decrypt still works.
    source_key._reset_cache_for_tests()
    monkeypatch.setenv("CONFIG_SECRET", "hunter2-very-secret")
    assert source_key.decrypt_pat(token) == "ghp_abc123"
    assert source_key.key_source() == "config_secret"

    # The file fallback must NOT have been materialised when env is set.
    assert not (tmp_path / ".source_key").exists()


def test_file_fallback_path(tmp_path):
    """No env secret → random key is written to data_dir with 0600."""
    token = source_key.encrypt_pat("ghp_xyz")

    key_path = tmp_path / ".source_key"
    assert key_path.exists()
    assert source_key.key_source() == "file"
    assert source_key.decrypt_pat(token) == "ghp_xyz"

    # Chmod is best-effort on Windows; only assert on POSIX.
    if os.name == "posix":
        mode = stat.S_IMODE(key_path.stat().st_mode)
        assert mode == 0o600


def test_no_key_material_raises(monkeypatch, tmp_path):
    """No env secret + unwritable data dir → SourceKeyUnavailableError."""
    blocked_parent = tmp_path / "blocked"
    blocked_file = blocked_parent / "paranoid.db"
    # Create the parent as a FILE so mkdir(parents=True) fails.
    blocked_parent.write_text("not-a-directory")
    monkeypatch.setattr(settings, "db_path", str(blocked_file))
    source_key._reset_cache_for_tests()

    with pytest.raises(source_key.SourceKeyUnavailableError):
        source_key.get_fernet()


def test_decrypt_with_wrong_key_raises(monkeypatch):
    """Ciphertext from key A cannot be decrypted under key B → PATDecryptionError."""
    monkeypatch.setenv("CONFIG_SECRET", "secret-A")
    token = source_key.encrypt_pat("token-value")

    source_key._reset_cache_for_tests()
    monkeypatch.setenv("CONFIG_SECRET", "secret-B")

    with pytest.raises(source_key.PATDecryptionError):
        source_key.decrypt_pat(token)


def test_encrypt_is_non_deterministic():
    """Fernet tokens include a timestamp/IV; two encrypts of same plaintext differ."""
    a = source_key.encrypt_pat("same-value")
    b = source_key.encrypt_pat("same-value")
    assert a != b
    assert source_key.decrypt_pat(a) == source_key.decrypt_pat(b) == "same-value"
