"""DTOs for admin endpoints."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str


class AdminLoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class AdminAuthOut(BaseModel):
    token: str
    admin: AdminOut


class AdminUserOut(BaseModel):
    """User listing as seen by admin (more fields than UserOut)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    phone: Optional[str] = None
    balance_seconds: int
    status: int
    created_at: datetime


class AdminUserListOut(BaseModel):
    items: list[AdminUserOut]
    total: int
    page: int
    size: int


class AdminLedgerItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    delta_seconds: int
    reason: str
    balance_after: int
    note: Optional[str] = None
    created_at: datetime


class AdminUserDetailOut(BaseModel):
    user: AdminUserOut
    recent_ledger: list[AdminLedgerItemOut]
    recent_sessions: list[dict] = []  # M2 will fill


class GrantIn(BaseModel):
    delta_seconds: int  # may be negative
    note: str = Field(..., min_length=1, max_length=255)


class UpdateUserIn(BaseModel):
    status: Optional[int] = Field(None, ge=0, le=1)
