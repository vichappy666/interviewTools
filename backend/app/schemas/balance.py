"""DTOs for balance ledger."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class LedgerItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delta_seconds: int
    reason: str
    ref_type: Optional[str] = None
    ref_id: Optional[int] = None
    balance_after: int
    note: Optional[str] = None
    created_at: datetime


class LedgerPageOut(BaseModel):
    items: list[LedgerItemOut]
    total: int
    page: int
    size: int
