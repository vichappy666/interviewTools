"""Pydantic DTOs for auth endpoints."""
from typing import Optional
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------- shared / response ----------

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    phone: Optional[str] = None
    balance_seconds: int


class AuthOut(BaseModel):
    token: str
    user: UserOut


# ---------- request bodies ----------

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-]{4,32}$")
_PHONE_RE = re.compile(r"^\d{6,15}$")


class RegisterIn(BaseModel):
    username: str = Field(..., min_length=4, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)
    phone: Optional[str] = Field(None, max_length=32)

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        if not _USERNAME_RE.match(v):
            raise ValueError("用户名仅支持字母/数字/下划线/横杠，长度 4-32")
        if v.isdigit():
            raise ValueError("用户名不能是纯数字")
        return v

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        has_alpha = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_alpha and has_digit):
            raise ValueError("密码必须同时包含字母和数字")
        return v

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not _PHONE_RE.match(v):
            raise ValueError("手机号格式不正确")
        return v


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class ResetPasswordIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    phone: str = Field(..., min_length=6, max_length=32)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        if not _PHONE_RE.match(v):
            raise ValueError("手机号格式不正确")
        return v

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        has_alpha = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_alpha and has_digit):
            raise ValueError("密码必须同时包含字母和数字")
        return v
