"""sessions 表 ORM 模型：一次面试会话。

注意：本类名为 ``Session``，与 ``sqlalchemy.orm.Session`` 同名。在调用方需要
同时引用两者时，建议用 ``from app.models.session import Session as SessionModel``
做别名导入。
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    func,
)

from app.db import Base


class Session(Base):
    __tablename__ = "sessions"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    started_at = Column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    ended_at = Column(DateTime(timezone=False), nullable=True)
    total_seconds = Column(Integer, nullable=False, default=0, server_default="0")
    end_reason = Column(
        Enum(
            "user_stop",
            "balance_zero",
            "idle_timeout",
            "admin_force",
            "error",
            name="session_end_reason",
        ),
        nullable=True,
    )
    status = Column(
        Enum("active", "ended", name="session_status"),
        nullable=False,
        default="active",
        server_default="active",
    )

    __table_args__ = (
        Index("ix_sessions_user_status", "user_id", "status"),
        Index("ix_sessions_user_started", "user_id", "started_at"),
    )
