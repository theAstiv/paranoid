"""Password hashing using argon2id.

argon2-cffi is lazy-imported inside each function so that importing this
module does NOT pull argon2 into the process.  This keeps the CLI import
graph clean — the CLI only needs the PAT sha256 path (stdlib hashlib), not
the full password-hashing stack.
"""

import logging


logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a password using argon2id.  Returns the encoded hash string."""
    from argon2 import PasswordHasher  # lazy — not in CLI path

    ph = PasswordHasher()
    return ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify *password* against an argon2id *password_hash*.

    Returns False on mismatch or any verification error.
    """
    from argon2 import PasswordHasher
    from argon2.exceptions import VerificationError, VerifyMismatchError

    ph = PasswordHasher()
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except VerificationError as exc:
        logger.warning(f"Password verification error: {exc}")
        return False


def needs_rehash(password_hash: str) -> bool:
    """Return True if the hash should be updated (e.g. parameters changed)."""
    from argon2 import PasswordHasher

    return PasswordHasher().check_needs_rehash(password_hash)
