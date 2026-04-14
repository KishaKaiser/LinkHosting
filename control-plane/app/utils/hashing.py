"""Shared password hashing utilities for site database credentials.

Uses argon2 as the primary scheme (no 72-byte limit, recommended for new
hashes) while keeping bcrypt listed as a deprecated scheme so that any
existing bcrypt-hashed db_password_hash values stored in the database can
still be verified and will be transparently re-hashed on next use.
"""
from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated=["bcrypt"],
)


def hash_db_password(password: str) -> str:
    """Hash a database password using argon2."""
    return pwd_context.hash(password)


def verify_db_password(password: str, hashed: str) -> bool:
    """Verify a database password against its stored hash."""
    return pwd_context.verify(password, hashed)
