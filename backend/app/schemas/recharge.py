"""DTOs for recharge orders（M3 T2）。

前端需要"金额字符串化"以避免 JS 浮点精度问题，因此 Decimal 字段在响应中
统一以 string 形式输出，由 ``field_serializer`` 处理。
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_serializer


class CreateOrderIn(BaseModel):
    """POST /api/recharge/orders 请求体。

    - amount_usdt：字符串（前端用 BigNumber/string 传），后端再 Decimal 解析
    - from_address：用户的 TRON 转出地址（T 开头、长度 34）
    """

    amount_usdt: str
    from_address: str


class SubmitHashIn(BaseModel):
    """POST /api/recharge/orders/{id}/submit 请求体。

    - tx_hash：用户上链转账后的交易哈希（64 hex；可带 0x 前缀，后端去前缀后再校）
    """

    tx_hash: str


class OrderRead(BaseModel):
    """订单详情/列表元素。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    amount_usdt: Decimal
    from_address: str
    to_address: str
    tx_hash: Optional[str] = None
    tx_amount_usdt: Optional[Decimal] = None
    granted_seconds: Optional[int] = None
    rate_per_usdt: Optional[int] = None
    status: str
    fail_reason: Optional[str] = None
    expires_at: datetime
    created_at: datetime
    succeeded_at: Optional[datetime] = None

    @field_serializer("amount_usdt")
    def _ser_amount(self, value: Decimal) -> str:
        return format(value, "f")

    @field_serializer("tx_amount_usdt")
    def _ser_tx_amount(self, value: Optional[Decimal]) -> Optional[str]:
        if value is None:
            return None
        return format(value, "f")


class OrderListResponse(BaseModel):
    items: list[OrderRead]
    total: int
    page: int
    size: int
