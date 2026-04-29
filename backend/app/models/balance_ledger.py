from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, Index, Integer, String, func

from app.db import Base


class BalanceLedger(Base):
    __tablename__ = "balance_ledger"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    delta_seconds = Column(Integer, nullable=False)
    reason = Column(
        Enum("recharge", "session", "admin_grant", "admin_revoke", "refund", name="ledger_reason"),
        nullable=False,
    )
    ref_type = Column(String(32), nullable=True)
    ref_id = Column(BigInteger, nullable=True)
    balance_after = Column(Integer, nullable=False)
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_ledger_user_created", "user_id", "created_at"),)
