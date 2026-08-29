from __future__ import annotations

import hashlib
import hmac
import secrets
import string

from pwdlib import PasswordHash

MIN_PASSWORD_LENGTH = 8
password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummypassword")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    hashed_password = hashed_password if hashed_password else DUMMY_HASH
    return password_hash.verify(password, hashed_password)


def validate_password_strength(password: str, *, username: str | None = None) -> str | None:
    """Return an error message if `password` is too weak, else None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Password must contain at least one letter and one digit."
    if username and username.strip().lower() in password.lower():
        return "Password must not contain the username."
    return None


def generate_registration_code() -> str:
    """Generate a 6-digit numeric one-time code using a CSPRNG."""
    return "".join(secrets.choice(string.digits) for _ in range(6))


def hash_code(code: str) -> str:
    """Hash a short-lived, rate-limited, single-use code."""
    return hashlib.sha256(code.encode()).hexdigest()


def verify_code(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_code(code), code_hash)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_refresh_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_refresh_token(token), token_hash)
