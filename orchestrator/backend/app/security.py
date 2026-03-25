from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from . import db
from .config import settings
from .models.user import User

SALT_BYTES = 16
PBKDF2_ITERATIONS = 210_000
TOKEN_BYTES = 32


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt_value = salt or secrets.token_hex(SALT_BYTES)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_value.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return salt_value, password_hash


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, password_hash = hash_password(password, salt)
    return hmac.compare_digest(password_hash, expected_hash)


def create_session_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def session_expiry_timestamp() -> str:
    return format_utc_timestamp(utc_now() + timedelta(hours=settings.session_ttl_hours))


def parse_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User:
    token = parse_bearer_token(authorization)
    user = db.get_user_by_token(token, format_utc_timestamp(utc_now()))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
