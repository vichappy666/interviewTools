"""/api/recharge/* REST endpoints（M3 T2 / T4）。

包含：
- POST /api/recharge/orders             创建充值订单
- GET  /api/recharge/orders             当前用户分页历史
- GET  /api/recharge/orders/{id}        单个订单详情
- POST /api/recharge/orders/{id}/submit 提交 tx_hash 同步核销
"""
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import configs as configs_module
from app.deps import get_current_user, get_db
from app.models.recharge_order import RechargeOrder
from app.models.user import User
from app.recharge.credit import credit_recharge
from app.recharge.tron import TronClient
from app.recharge.verifier import verify_tx
from app.schemas.recharge import (
    CreateOrderIn,
    OrderListResponse,
    OrderRead,
    SubmitHashIn,
)


logger = logging.getLogger(__name__)


_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")


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


# ---------------- POST /orders/{id}/submit ----------------


async def _broadcast_balance_to_user(user_id: int, balance: int) -> None:
    """把 balance_update 广播给该用户所有 active session ws。

    单条 broadcast 失败不抛、不影响主流程（充值已 commit）。
    """
    from app.sessions.manager import manager as session_manager  # 局部 import 避免循环

    for rt in session_manager.list_for_user(user_id):
        try:
            await session_manager.broadcast(
                rt.id,
                {"type": "balance_update", "balance_seconds": balance},
            )
        except Exception:  # noqa: BLE001 — broadcast 失败不影响入账
            logger.warning(
                "broadcast balance_update to session %s failed", rt.id, exc_info=True
            )


@router.post("/orders/{order_id}/submit", response_model=OrderRead)
async def submit_order_hash(
    order_id: int,
    body: SubmitHashIn,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderRead:
    """用户提交 tx_hash → 同步调 verify_tx → 通过则同事务里加余额/写 ledger/改订单。

    严格按 spec 顺序：load → status check → expiry check → hash format → mark verifying
    → call verify_tx (try/finally close client) → on success credit + commit + broadcast。
    """
    # 1. load + 鉴权（统一 404 避免泄露订单是否存在）
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

    # 2. 必须 pending
    if order.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "ORDER_NOT_PENDING",
                    "message": f"订单当前状态为 {order.status}，不能再次提交",
                }
            },
        )

    # 3. expires_at 检查
    now = datetime.utcnow()
    if now > order.expires_at:
        order.status = "expired"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {"code": "ORDER_EXPIRED", "message": "订单已过期"}
            },
        )

    # 4. 校验 tx_hash 格式（去空白 + 去 0x 前缀 + 64 hex）
    raw = (body.tx_hash or "").strip()
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    if not _HEX64_RE.match(raw):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_TX_HASH",
                    "message": "tx_hash 必须是 64 位十六进制字符串",
                }
            },
        )
    tx_hash_normalized = raw.lower()

    # 5. UPDATE order SET tx_hash, status='verifying'
    order.tx_hash = tx_hash_normalized
    order.status = "verifying"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # rollback 后内存里 order 可能仍带 verifying，不再 db.refresh — 直接报错
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "HASH_ALREADY_USED",
                    "message": "该 tx_hash 已被其他订单使用",
                }
            },
        )
    db.refresh(order)

    # 6. 构造 TronClient
    network = configs_module.get("recharge.network", "shasta")
    api_key = configs_module.get("recharge.tron_api_key") or None
    tron = TronClient(network=network, api_key=api_key)

    # 7. try/finally 调 verify_tx
    try:
        try:
            result = verify_tx(
                tron=tron,
                network=network,
                tx_hash=tx_hash_normalized,
                expected_to=order.to_address,
                expected_from=order.from_address,
                min_amount_usdt=Decimal(order.amount_usdt),
                expires_at=order.expires_at,
            )
        except (httpx.HTTPError, httpx.RequestError) as e:
            order.status = "failed"
            order.fail_reason = f"链上 RPC 失败: {repr(e)[:200]}"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": {
                        "code": "TRON_RPC_ERROR",
                        "message": "链上节点暂时不可用，请稍后再试",
                    }
                },
            )
    finally:
        tron.close()

    # 8. 处理 verify_tx 结果
    if not result.ok:
        order.status = "failed"
        order.fail_reason = f"{result.code}: {result.message}"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {"code": result.code, "message": result.message}
            },
        )

    # 成功：同事务内 credit + 改 order
    granted_seconds = int(Decimal(result.tx_amount_usdt) * order.rate_per_usdt)
    new_balance = credit_recharge(
        db,
        user_id=current.id,
        delta_seconds=granted_seconds,
        order_id=order.id,
    )
    order.tx_amount_usdt = result.tx_amount_usdt
    order.granted_seconds = granted_seconds
    order.status = "succeeded"
    order.succeeded_at = datetime.utcnow()
    db.commit()
    db.refresh(order)

    # broadcast balance_update（失败不影响主流程）
    try:
        await _broadcast_balance_to_user(current.id, new_balance)
    except Exception:  # noqa: BLE001
        logger.warning("broadcast balance_update failed", exc_info=True)

    return OrderRead.model_validate(order)
