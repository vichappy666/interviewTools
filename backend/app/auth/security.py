"""bcrypt + JWT helpers。"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from app.config import settings


# ---------- bcrypt ----------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------- JWT ----------

def _make_token(subject_id: int, type_: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        # PyJWT >=2.10 enforces RFC 7519: `sub` must be a string. Cast on encode,
        # cast back to int on decode so callers always see an int subject id.
        "sub": str(subject_id),
        "type": type_,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.jwt_expire_days)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def make_user_token(user_id: int) -> str:
    return _make_token(user_id, "user")


def make_admin_token(admin_id: int) -> str:
    return _make_token(admin_id, "admin")


def decode_token(token: str) -> Optional[dict]:
    """Returns payload dict (with sub coerced back to int), or None if expired/invalid."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    sub = payload.get("sub")
    if sub is not None:
        try:
            payload["sub"] = int(sub)
        except (TypeError, ValueError):
            return None
    return payload
