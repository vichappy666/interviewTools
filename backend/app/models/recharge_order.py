"""recharge_orders 表 ORM 模型：USDT 充值订单。

每条订单代表用户一次充值流程：从用户在前端声明应付金额和转出钱包地址开始，
到链上 tx_hash 提交、核销成功并加余额结束。详见 spec 第 2.2 节。
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)

from app.db import Base


class RechargeOrder(Base):
    __tablename__ = "recharge_orders"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    amount_usdt = Column(Numeric(20, 6), nullable=False)
    from_address = Column(String(64), nullable=False)
    to_address = Column(String(64), nullable=False)
    tx_hash = Column(String(80), nullable=True)
    tx_amount_usdt = Column(Numeric(20, 6), nullable=True)
    granted_seconds = Column(Integer, nullable=True)
    rate_per_usdt = Column(Integer, nullable=True)
    status = Column(
        Enum(
            "pending",
            "submitted",
            "verifying",
            "succeeded",
            "failed",
            "expired",
            name="recharge_status",
        ),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    fail_reason = Column(String(255), nullable=True)
    expires_at = Column(DateTime(timezone=False), nullable=False)
    created_at = Column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    succeeded_at = Column(DateTime(timezone=False), nullable=True)

    __table_args__ = (
        Index("ix_recharge_orders_user_created", "user_id", "created_at"),
        Index("ix_recharge_orders_status_expires", "status", "expires_at"),
        UniqueConstraint("tx_hash", name="uq_recharge_orders_tx_hash"),
    )
