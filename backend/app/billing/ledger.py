"""Authoritative ledger writer.

Every balance change goes through grant() which:
  1. Row-locks the user (SELECT ... FOR UPDATE — no-op on SQLite tests but
     correct on MySQL)
  2. Computes new balance = old + delta_seconds
  3. Rejects (raises 400 INSUFFICIENT_BALANCE) if new < 0
  4. INSERTs a balance_ledger row with balance_after = new balance
  5. UPDATEs users.balance_seconds = new
  6. Commits and returns new balance
"""
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.balance_ledger import BalanceLedger
from app.models.user import User


VALID_REASONS = {"recharge", "session", "admin_grant", "admin_revoke", "refund"}


def grant(
    db: Session,
    user_id: int,
    delta_seconds: int,
    reason: str,
    ref_type: Optional[str] = None,
    ref_id: Optional[int] = None,
    note: Optional[str] = None,
) -> int:
    """Atomically apply a balance change. Returns new balance_seconds.

    Raises HTTPException(400, INSUFFICIENT_BALANCE) if the operation would
    drop balance below zero.
    """
    if reason not in VALID_REASONS:
        raise ValueError(f"invalid reason: {reason!r}")

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .with_for_update()
        .one_or_none()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "USER_NOT_FOUND", "message": "用户不存在"}},
        )

    new_balance = (user.balance_seconds or 0) + delta_seconds
    if new_balance < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INSUFFICIENT_BALANCE",
                    "message": "余额不足",
                }
            },
        )

    entry = BalanceLedger(
        user_id=user.id,
        delta_seconds=delta_seconds,
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
        balance_after=new_balance,
        note=note,
    )
    db.add(entry)

    user.balance_seconds = new_balance
    db.commit()
    db.refresh(user)
    return new_balance
