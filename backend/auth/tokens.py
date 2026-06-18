"""JWT access tokens and Personal Access Tokens (PATs).

PyJWT is lazy-imported inside functions so that importing this module does NOT
pull jwt into the process.  The CLI only needs the PAT sha256 path (stdlib
hashlib + secrets) — no PyJWT required on the CLI import path.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta


logger = logging.getLogger(__name__)

# Access token lifetime
ACCESS_TOKEN_EXPIRE_MINUTES = 15
# Refresh token lifetime
REFRESH_TOKEN_EXPIRE_DAYS = 7

# PAT format: pat_<token_id>_<32-byte-random-hex>
_PAT_PREFIX = "pat_"

# Module-level ephemeral key — generated once per process when neither
# JWT_SECRET nor CONFIG_SECRET is configured.  Restarts invalidate tokens.
_ephemeral_jwt_key: str | None = None


def _get_jwt_key() -> str:
    """Resolve the JWT signing key.

    Priority:
    1. JWT_SECRET env var / settings.jwt_secret
    2. PBKDF2 derivation from CONFIG_SECRET (salt "paranoid:jwt:v1")
    3. Ephemeral random key (logged as warning; restarts invalidate JWTs)
    """
    global _ephemeral_jwt_key

    from backend.config import settings

    if settings.jwt_secret:
        return settings.jwt_secret

    if settings.config_secret:
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            settings.config_secret.encode(),
            b"paranoid:jwt:v1",
            iterations=100_000,
        )
        return dk.hex()

    if _ephemeral_jwt_key is None:
        _ephemeral_jwt_key = secrets.token_hex(32)
        logger.warning(
            "JWT_SECRET not set — using an ephemeral per-process key. "
            "All JWTs are invalidated on restart. "
            "Set JWT_SECRET (or CONFIG_SECRET) for persistent sessions."
        )
    return _ephemeral_jwt_key


def create_access_token(user_id: str, username: str, is_admin: bool) -> str:
    """Create a 15-min HS256 JWT access token."""
    import jwt  # lazy — PyJWT

    now = datetime.now(UTC)
    exp = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "username": username,
        "is_admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _get_jwt_key(), algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT.  Raises jwt.InvalidTokenError on failure."""
    import jwt  # lazy — PyJWT

    return jwt.decode(token, _get_jwt_key(), algorithms=["HS256"])


def create_refresh_token() -> tuple[str, str]:
    """Create a 7-day refresh token.

    Returns:
        (jti, raw_token) — store jti in the sessions table; give raw_token
        to the client once (it is not stored).

    Token format: ``<jti>:<random_bytes>`` so the jti can be extracted from
    the raw token for a PK lookup without a full table scan.
    """
    jti = str(uuid.uuid4())
    raw = secrets.token_urlsafe(48)
    return jti, f"{jti}:{raw}"


def parse_refresh_token_jti(raw_token: str) -> str | None:
    """Extract the jti from a raw refresh token.  Returns None on bad format."""
    parts = raw_token.split(":", 1)
    if len(parts) != 2:
        return None
    return parts[0]


def create_pat() -> tuple[str, str, str]:
    """Create a new Personal Access Token.

    Returns:
        (token_id, raw_token, token_hash)
        token_id  — UUID; use as the PK row in personal_access_tokens.
        raw_token — full string returned to the user once; never stored.
        token_hash — sha256(raw_token); stored in the DB for validation.

    Token format: ``pat_<token_id>_<32-byte-random-hex>`` so the token_id
    can be extracted with :func:`parse_pat_token_id` for an O(1) PK lookup,
    followed by a single sha256 comparison — exactly what GitHub/GitLab/Stripe
    do.  argon2 is not used because PATs are 256-bit random secrets with no
    brute-force surface.
    """
    token_id = str(uuid.uuid4())
    random_hex = secrets.token_hex(32)
    raw_token = f"{_PAT_PREFIX}{token_id}_{random_hex}"
    return token_id, raw_token, hash_pat(raw_token)


def hash_pat(raw_token: str) -> str:
    """SHA-256 hash of a raw PAT string for DB storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def is_pat(token: str) -> bool:
    """Return True if *token* looks like a PAT (starts with ``pat_``)."""
    return token.startswith(_PAT_PREFIX)


def parse_pat_token_id(raw_token: str) -> str | None:
    """Extract the token_id UUID from a PAT for O(1) PK lookup.

    Returns None if the format does not match ``pat_<id>_<random>``.
    """
    if not is_pat(raw_token):
        return None
    without_prefix = raw_token[len(_PAT_PREFIX) :]
    parts = without_prefix.split("_", 1)
    if len(parts) != 2:
        return None
    return parts[0]
