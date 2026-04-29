"""GET /api/balance/ledger — paginated ledger for current user."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.balance_ledger import BalanceLedger
from app.models.user import User
from app.schemas.balance import LedgerItemOut, LedgerPageOut


router = APIRouter(prefix="/api/balance", tags=["balance"])


@router.get("/ledger", response_model=LedgerPageOut)
def list_ledger(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LedgerPageOut:
    q = (
        db.query(BalanceLedger)
        .filter(BalanceLedger.user_id == current.id)
        .order_by(BalanceLedger.created_at.desc(), BalanceLedger.id.desc())
    )
    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    return LedgerPageOut(
        items=[LedgerItemOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )
