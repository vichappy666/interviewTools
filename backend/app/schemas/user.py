"""DTOs for /api/users/me*."""
from typing import Optional
import re

from pydantic import BaseModel, Field, field_validator


_PHONE_RE = re.compile(r"^\d{6,15}$")


class UpdateMeIn(BaseModel):
    phone: Optional[str] = Field(None, max_length=32)

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not _PHONE_RE.match(v):
            raise ValueError("手机号格式不正确")
        return v


class ChangePasswordIn(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        has_alpha = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_alpha and has_digit):
            raise ValueError("密码必须同时包含字母和数字")
        return v
