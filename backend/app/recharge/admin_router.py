"""/api/admin/recharge/* 管理后台充值订单管理 endpoints（M3 T5）。

包含：
- GET  /api/admin/recharge/orders                       订单列表（status / user_id 过滤）
- POST /api/admin/recharge/orders/{id}/force-success    强制核销成功并入账
- POST /api/admin/recharge/orders/{id}/force-fail       强制标记失败
- POST /api/admin/recharge/orders/{id}/retry            把已失败订单重置为 pending

所有 endpoint 走 ``Depends(get_current_admin)`` 鉴权，每次操作均写 admin_audit_log。
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.audit import write as audit_write
from app.deps import get_current_admin, get_db
from app.models.admin import Admin
from app.models.recharge_order import RechargeOrder
from app.models.user import User
from app.recharge.credit import credit_recharge
from app.recharge.router import _broadcast_balance_to_user
from app.schemas.recharge import (
    AdminOrderListResponse,
    AdminOrderRead,
    ForceActionIn,
)


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/admin/recharge", tags=["admin-recharge"])


_FORCE_SUCCESS_ALLOWED = {"pending", "submitted", "verifying", "failed", "expired"}
_FORCE_FAIL_ALLOWED = {"pending", "submitted", "verifying"}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _order_to_dict(order: RechargeOrder, username: str | None) -> dict:
    """把 ORM RechargeOrder 转成 AdminOrderRead 接受的 dict。

    所有字段显式列出，避免把 sqlalchemy 内部状态序列化进去。
    """
    return {
        "id": order.id,
        "user_id": order.user_id,
        "amount_usdt": order.amount_usdt,
        "from_address": order.from_address,
        "to_address": order.to_address,
        "tx_hash": order.tx_hash,
        "tx_amount_usdt": order.tx_amount_usdt,
        "granted_seconds": order.granted_seconds,
        "rate_per_usdt": order.rate_per_usdt,
        "status": order.status,
        "fail_reason": order.fail_reason,
        "expires_at": order.expires_at,
        "created_at": order.created_at,
        "succeeded_at": order.succeeded_at,
        "username": username,
    }


def _load_order_or_404(db: Session, order_id: int) -> RechargeOrder:
    order = db.query(RechargeOrder).filter(RechargeOrder.id == order_id).one_or_none()
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "ORDER_NOT_FOUND", "message": "订单不存在"}},
        )
    return order


def _username_for(db: Session, user_id: int) -> str | None:
    row = (
        db.query(User.username)
        .filter(User.id == user_id)
        .one_or_none()
    )
    return row[0] if row else None


# ---------------- GET /orders ----------------

@router.get("/orders", response_model=AdminOrderListResponse)
def list_orders_admin(
    status_: str | None = Query(None, alias="status", max_length=20),
    user_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminOrderListResponse:
    q = (
        db.query(RechargeOrder, User.username)
        .outerjoin(User, User.id == RechargeOrder.user_id)
    )
    if status_:
        q = q.filter(RechargeOrder.status == status_)
    if user_id is not None:
        q = q.filter(RechargeOrder.user_id == user_id)

    total = q.count()
    rows = (
        q.order_by(RechargeOrder.created_at.desc(), RechargeOrder.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    items = [
        AdminOrderRead.model_validate(_order_to_dict(order, username))
        for order, username in rows
    ]
    return AdminOrderListResponse(items=items, total=total, page=page, size=size)


# ---------------- POST /orders/{id}/force-success ----------------

@router.post("/orders/{order_id}/force-success", response_model=AdminOrderRead)
async def force_success(
    order_id: int,
    body: ForceActionIn,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminOrderRead:
    order = _load_order_or_404(db, order_id)
    if order.status not in _FORCE_SUCCESS_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "ORDER_NOT_FORCEABLE",
                    "message": f"订单当前状态为 {order.status}，不能强制核销",
                }
            },
        )

    note = body.note
    granted_seconds = int(Decimal(order.amount_usdt) * order.rate_per_usdt)

    # 同事务：credit + 改 order + audit
    new_balance = credit_recharge(
        db,
        user_id=order.user_id,
        delta_seconds=granted_seconds,
        order_id=order.id,
        note=f"admin force: {note}",
    )
    if order.tx_amount_usdt is None:
        order.tx_amount_usdt = order.amount_usdt
    order.granted_seconds = granted_seconds
    order.status = "succeeded"
    order.succeeded_at = datetime.utcnow()
    order.fail_reason = None

    audit_write(
        db,
        admin_id=admin.id,
        action="force_recharge_success",
        target_type="recharge_order",
        target_id=order.id,
        payload={"granted_seconds": granted_seconds, "note": note},
        ip=_client_ip(request),
        note=note,
    )
    db.commit()
    db.refresh(order)

    # broadcast（commit 之后；失败不影响主流程）
    try:
        await _broadcast_balance_to_user(order.user_id, new_balance)
    except Exception:  # noqa: BLE001
        logger.warning("broadcast balance_update failed", exc_info=True)

    username = _username_for(db, order.user_id)
    return AdminOrderRead.model_validate(_order_to_dict(order, username))


# ---------------- POST /orders/{id}/force-fail ----------------

@router.post("/orders/{order_id}/force-fail", response_model=AdminOrderRead)
def force_fail(
    order_id: int,
    body: ForceActionIn,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminOrderRead:
    order = _load_order_or_404(db, order_id)
    if order.status not in _FORCE_FAIL_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "ORDER_NOT_FORCEABLE",
                    "message": f"订单当前状态为 {order.status}，不能强制标记失败",
                }
            },
        )

    note = body.note
    order.status = "failed"
    order.fail_reason = f"admin force: {note}"

    audit_write(
        db,
        admin_id=admin.id,
        action="force_recharge_fail",
        target_type="recharge_order",
        target_id=order.id,
        payload={"note": note},
        ip=_client_ip(request),
        note=note,
    )
    db.commit()
    db.refresh(order)

    username = _username_for(db, order.user_id)
    return AdminOrderRead.model_validate(_order_to_dict(order, username))


# ---------------- POST /orders/{id}/retry ----------------

@router.post("/orders/{order_id}/retry", response_model=AdminOrderRead)
def retry_order(
    order_id: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminOrderRead:
    order = _load_order_or_404(db, order_id)
    if order.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "ORDER_NOT_FORCEABLE",
                    "message": f"订单当前状态为 {order.status}，无法重置为 pending",
                }
            },
        )

    order.status = "pending"
    order.fail_reason = None
    order.tx_hash = None  # 清掉避免 UNIQUE 卡住

    audit_write(
        db,
        admin_id=admin.id,
        action="retry_recharge_order",
        target_type="recharge_order",
        target_id=order.id,
        payload={},
        ip=_client_ip(request),
    )
    db.commit()
    db.refresh(order)

    username = _username_for(db, order.user_id)
    return AdminOrderRead.model_validate(_order_to_dict(order, username))
