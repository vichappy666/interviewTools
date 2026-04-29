"""/api/recharge/* REST endpoints（M3 T2）。

包含：
- POST /api/recharge/orders        创建充值订单
- GET  /api/recharge/orders        当前用户分页历史
- GET  /api/recharge/orders/{id}   单个订单详情
"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import configs as configs_module
from app.deps import get_current_user, get_db
from app.models.recharge_order import RechargeOrder
from app.models.user import User
from app.schemas.recharge import CreateOrderIn, OrderListResponse, OrderRead


router = APIRouter(prefix="/api/recharge", tags=["recharge"])


# ---------------- POST /orders ----------------

@router.post("/orders", response_model=OrderRead)
def create_order(
    body: CreateOrderIn,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderRead:
    # 1. 解析 + 校验金额
    try:
        amount = Decimal(body.amount_usdt)
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {"code": "INVALID_AMOUNT", "message": "金额格式不合法"}
            },
        )

    min_amount = Decimal(str(configs_module.get("recharge.min_amount_usdt", 1)))
    if amount < min_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "AMOUNT_TOO_SMALL",
                    "message": f"金额不能低于 {min_amount} USDT",
                }
            },
        )

    # 2. 校验 from_address 基础格式（不调链）
    from_addr = (body.from_address or "").strip()
    if (not from_addr) or len(from_addr) != 34 or not from_addr.startswith("T"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_FROM_ADDRESS",
                    "message": "转出地址格式不合法",
                }
            },
        )

    # 3. 读 to_address，必须配置
    to_address = configs_module.get("recharge.to_address")
    if not to_address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "RECHARGE_NOT_CONFIGURED",
                    "message": "平台收款地址未配置，请联系管理员",
                }
            },
        )

    # 4. 读 rate_per_usdt（默认 60，转 int）
    rate_per_usdt = int(configs_module.get("recharge.rate_per_usdt", 60))

    # 5. INSERT
    order = RechargeOrder(
        user_id=current.id,
        amount_usdt=amount,
        from_address=from_addr,
        to_address=to_address,
        rate_per_usdt=rate_per_usdt,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    return OrderRead.model_validate(order)


# ---------------- GET /orders ----------------

@router.get("/orders", response_model=OrderListResponse)
def list_orders(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderListResponse:
    q = (
        db.query(RechargeOrder)
        .filter(RechargeOrder.user_id == current.id)
        .order_by(RechargeOrder.created_at.desc(), RechargeOrder.id.desc())
    )
    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    return OrderListResponse(
        items=[OrderRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


# ---------------- GET /orders/{id} ----------------

@router.get("/orders/{order_id}", response_model=OrderRead)
def get_order(
    order_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderRead:
    order = (
        db.query(RechargeOrder)
        .filter(
            RechargeOrder.id == order_id,
            RechargeOrder.user_id == current.id,
        )
        .one_or_none()
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {"code": "ORDER_NOT_FOUND", "message": "订单不存在"}
            },
        )
    return OrderRead.model_validate(order)
