"""session_qa 表 ORM 模型：单次问答记录（三段并行回答）。"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects import mysql

from app.db import Base


class SessionQA(Base):
    __tablename__ = "session_qa"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    session_id = Column(BigInteger, ForeignKey("sessions.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer_key_points = Column(
        Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=True
    )
    answer_script = Column(
        Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=True
    )
    answer_full = Column(
        Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=True
    )
    asked_at = Column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    finished_at = Column(DateTime(timezone=False), nullable=True)
    source = Column(
        Enum("detected", "manual", name="session_qa_source"),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_session_qa_session_asked", "session_id", "asked_at"),
    )
