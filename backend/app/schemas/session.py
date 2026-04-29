"""DTOs for sessions / session_qa。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    started_at: datetime
    ended_at: Optional[datetime] = None
    total_seconds: int
    end_reason: Optional[str] = None
    status: str


class SessionQARead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    question: str
    answer_key_points: Optional[str] = None
    answer_script: Optional[str] = None
    answer_full: Optional[str] = None
    asked_at: datetime
    finished_at: Optional[datetime] = None
    source: str


class SessionStartResponse(BaseModel):
    session_id: int
    ws_url: str


class SessionListResponse(BaseModel):
    items: list[SessionRead]
    total: int
    page: int
    size: int
