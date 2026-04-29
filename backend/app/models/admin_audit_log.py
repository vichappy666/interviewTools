"""管理员操作审计日志表。"""
from sqlalchemy import JSON, BigInteger, Column, DateTime, Index, Integer, String, func

from app.db import Base


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    admin_id = Column(BigInteger, nullable=False)
    action = Column(String(64), nullable=False)
    target_type = Column(String(32), nullable=False)
    target_id = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=True)
    ip = Column(String(64), nullable=True)
    note = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_audit_admin_created", "admin_id", "created_at"),
        Index("ix_audit_target", "target_type", "target_id"),
    )
