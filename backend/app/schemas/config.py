"""DTOs for /api/admin/configs endpoints."""
from typing import Any

from pydantic import BaseModel


class ConfigPutIn(BaseModel):
    value: Any


class ConfigItemOut(BaseModel):
    key: str
    value: Any
