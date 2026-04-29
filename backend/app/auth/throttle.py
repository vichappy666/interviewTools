"""Rate limiter backed by `auth_throttle` table.

Strategy: one row per (scope, time-window). Each call atomically
INSERT-or-UPDATE the row, comparing count. If count >= limit and the window
has not expired, reject.
"""
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth_throttle import AuthThrottle


def consume(db: Session, scope: str, limit: int, window_seconds: int) -> None:
    """Raise 429 if rate exceeded; otherwise increment counter."""
    now = datetime.utcnow()
    row = db.query(AuthThrottle).filter(AuthThrottle.scope == scope).one_or_none()

    if row is None:
        row = AuthThrottle(
            scope=scope, count=1, reset_at=now + timedelta(seconds=window_seconds)
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # someone else inserted concurrently; reload and fall through
            row = db.query(AuthThrottle).filter(AuthThrottle.scope == scope).one()
        else:
            return

    # Window expired? Reset.
    if row.reset_at <= now:
        row.count = 1
        row.reset_at = now + timedelta(seconds=window_seconds)
        db.commit()
        return

    # Within window — check limit.
    if row.count >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后再试"}},
        )

    row.count += 1
    db.commit()
