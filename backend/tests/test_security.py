"""Tests for app.auth.security pure helpers (no DB needed)."""
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.auth.security import (
    decode_token,
    hash_password,
    make_admin_token,
    make_user_token,
    verify_password,
)
from app.config import settings


def test_hash_and_verify_password_round_trip():
    h = hash_password("hunter2")
    assert h.startswith("$2b$")
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_verify_password_handles_garbage():
    assert verify_password("anything", "not-a-hash") is False
    assert verify_password("anything", "") is False


def test_make_user_token_decodes_with_user_type():
    tok = make_user_token(42)
    payload = decode_token(tok)
    assert payload is not None
    assert payload["sub"] == 42
    assert payload["type"] == "user"
    assert payload["exp"] > payload["iat"]


def test_make_admin_token_decodes_with_admin_type():
    tok = make_admin_token(7)
    payload = decode_token(tok)
    assert payload is not None
    assert payload["type"] == "admin"


def test_decode_token_rejects_garbage():
    assert decode_token("not.a.token") is None


def test_decode_token_rejects_expired():
    # Manually craft a token already expired.
    now = datetime.now(timezone.utc)
    payload = {
        "sub": 1,
        "type": "user",
        "iat": int((now - timedelta(days=10)).timestamp()),
        "exp": int((now - timedelta(days=1)).timestamp()),
    }
    expired = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    assert decode_token(expired) is None
