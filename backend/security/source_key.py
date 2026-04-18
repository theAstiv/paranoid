"""Fernet key management for at-rest credential encryption.

Resolves a Fernet key from one of two sources, in this order:

1. The ``CONFIG_SECRET`` environment variable, stretched via PBKDF2-HMAC-SHA256
   (100k iterations, static app-scoped salt). The static salt is deliberate —
   the derived key must be reproducible across restarts. PBKDF2's role here is
   stretching a potentially low-entropy user secret into 32 bytes, not
   providing per-record salt security.
2. A 32-byte random key persisted at ``<data_dir>/.source_key`` (0600).
   Generated on first use when no env secret is set.

The two sources are **not interchangeable** — once a deployment has encrypted
data under one, switching silently corrupts decryption. Key-source tracking
is enforced by callers (via the ``config`` table's ``pat_key_source`` row).
"""

import base64
import logging
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from backend.config import settings


logger = logging.getLogger(__name__)

_PBKDF2_SALT = b"paranoid:source_key:v1"
_PBKDF2_ITERATIONS = 100_000
_KEY_FILENAME = ".source_key"
_KEY_BYTES = 32

_fernet_cache: Fernet | None = None
_cached_source: str | None = None


class SourceKeyUnavailableError(RuntimeError):
    """No key material could be produced (no env secret, non-writable data dir)."""


class PATDecryptionError(RuntimeError):
    """Decryption failed — wrong key, corrupt ciphertext, or key-source switch."""


def _data_dir() -> Path:
    return Path(settings.db_path).parent


def _derive_key_from_secret(secret: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_BYTES,
        salt=_PBKDF2_SALT,
        iterations=_PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))


def _load_or_create_file_key(data_dir: Path) -> bytes:
    key_path = data_dir / _KEY_FILENAME
    if key_path.exists():
        raw = key_path.read_bytes()
        if len(raw) != _KEY_BYTES:
            msg = f"{key_path} has wrong length ({len(raw)} bytes, expected {_KEY_BYTES})"
            raise SourceKeyUnavailableError(msg)
        return base64.urlsafe_b64encode(raw)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        raw = secrets.token_bytes(_KEY_BYTES)
        key_path.write_bytes(raw)
        os.chmod(key_path, 0o600)
    except OSError as exc:
        msg = (
            "Set CONFIG_SECRET or allow writable data dir to store credentials "
            f"(writing {key_path} failed: {exc})"
        )
        raise SourceKeyUnavailableError(msg) from exc
    return base64.urlsafe_b64encode(raw)


def _resolve() -> tuple[Fernet, str]:
    """Resolve Fernet + source label. Never cached — call ``get_fernet`` instead."""
    secret = os.environ.get("CONFIG_SECRET", "").strip() or settings.config_secret.strip()
    if secret:
        return Fernet(_derive_key_from_secret(secret)), "config_secret"
    key = _load_or_create_file_key(_data_dir())
    return Fernet(key), "file"


def get_fernet() -> Fernet:
    """Return a cached Fernet for the active key source.

    Raises:
        SourceKeyUnavailableError: when no env secret is set and the data dir
            is not writable.
    """
    global _fernet_cache, _cached_source
    if _fernet_cache is None:
        _fernet_cache, _cached_source = _resolve()
    return _fernet_cache


def key_source() -> str:
    """Return ``"config_secret"`` or ``"file"`` — the active key source label.

    Resolves the key if not already cached. Used by CRUD to persist the
    ``pat_key_source`` marker and detect cross-restart switches.
    """
    get_fernet()
    assert _cached_source is not None  # populated by get_fernet above
    return _cached_source


def encrypt_str(plaintext: str) -> bytes:
    return get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_str(ciphertext: bytes) -> str:
    try:
        return get_fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise PATDecryptionError("Credential decryption failed") from exc


# Credential-specific aliases. Distinct names keep call sites self-documenting
# even though PATs and API keys share the same Fernet under the hood.
def encrypt_pat(plaintext: str) -> bytes:
    return encrypt_str(plaintext)


def decrypt_pat(ciphertext: bytes) -> str:
    return decrypt_str(ciphertext)


def _reset_cache_for_tests() -> None:
    """Test-only hook. Resets cached Fernet so a test can swap key sources."""
    global _fernet_cache, _cached_source
    _fernet_cache = None
    _cached_source = None
