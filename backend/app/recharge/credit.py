"""充值入账 helper：在调用方事务内写 ledger + 更新 user.balance_seconds，不 commit。

与 billing.ledger.grant 区别：grant 自带 commit，适合扣费独立事务；这里要把
ledger + balance + order.status 三件事在同一事务内 commit，所以拆出 no-commit 版。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.balance_ledger import BalanceLedger
from app.models.user import User


def credit_recharge(
    db: Session,
    *,
    user_id: int,
    delta_seconds: int,
    order_id: int,
    note: str | None = None,
) -> int:
    """加余额 + 写 ledger（**不 commit**）。返回新 balance。

    要求：调用方负责开/关事务，且必须紧接 db.commit()。
    """
    if delta_seconds <= 0:
        raise ValueError(f"delta_seconds must be positive, got {delta_seconds}")
    user = (
        db.query(User).filter(User.id == user_id).with_for_update().one_or_none()
    )
    if user is None:
        raise ValueError(f"user {user_id} not found")
    new_balance = (user.balance_seconds or 0) + delta_seconds
    db.add(
        BalanceLedger(
            user_id=user.id,
            delta_seconds=delta_seconds,
            reason="recharge",
            ref_type="recharge",
            ref_id=order_id,
            balance_after=new_balance,
            note=note,
        )
    )
    user.balance_seconds = new_balance
    return new_balance
