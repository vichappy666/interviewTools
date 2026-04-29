"""链上充值校验器（M3 T3）。

核心职责：拿到 (tx_hash, expected_to, expected_from, min_amount, expires_at)，
通过 TronGrid 查询并跑 7 项校验，返回 VerifyResult。任何一项失败立即返回，不继续。

关键决策：
- 不引入 base58 / tronpy 依赖，自己用标准库 hashlib 实现 base58check 解码；
- 同步调用 httpx，verifier 在 FastAPI 同步 handler 里被调用；
- USDT-TRC20 在 mainnet 用官方合约；shasta 用 JST 测试合约（T10 端到端会再校）。

7 项校验顺序（来自 spec/M3-T3）：
1. tx 存在（gettransactioninfobyid 非空且有 id）
2. receipt.result == SUCCESS
3. contract_address 是期望的 USDT 合约（地址等价比较：base58 ↔ hex）
4. transfer(address,uint256) 解析出 to/from 与 expected 匹配（method_id=a9059cbb）
5. 金额 >= min_amount_usdt（USDT 6 位小数）
6. now_block - tx_block >= confirmations_required
7. blockTimeStamp <= expires_at（不晚于订单过期时刻）
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .tron import TronClient


# ---------------- 常量 ----------------

#: USDT-TRC20 主网合约地址（base58）
USDT_CONTRACT_MAINNET = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# TODO(T10): Shasta 占位合约，主网切换前 admin 需校验合约地址。
#: Shasta 测试网占位（JST 测试合约；T10 端到端实测时会再校验）
USDT_CONTRACT_SHASTA = "TG3XXyExBkPp9nzdajDZsozEu4BkaSJozs"

#: USDT 精度（6 位小数）。raw_amount / 10^6 = USDT 金额
USDT_DECIMALS = 6

#: TRC20 transfer(address,uint256) 的 method id
TRC20_TRANSFER_METHOD_ID = "a9059cbb"


# ---------------- VerifyResult ----------------


@dataclass
class VerifyResult:
    ok: bool
    code: str = ""
    message: str = ""
    tx_amount_usdt: Decimal | None = None  # 通过时回填


# ---------------- base58check 手写实现 ----------------

_B58_ALPHABET = (
    "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
)


def _b58decode_check(s: str) -> bytes:
    """Bitcoin/Tron base58check 解码。返回 payload（去掉 4 字节 checksum）。

    步骤：
    1. base58 字符 → 大整数 → bytes（保留前导零：每个前导 '1' 字符 → 一个 0 字节）
    2. 取最后 4 字节为 checksum，前面是 payload
    3. sha256(sha256(payload))[:4] 必须等于 checksum，否则抛 ValueError

    任何不在 base58 字母表里的字符也会抛 ValueError（来自 str.index）。
    """
    if not s:
        raise ValueError("base58check: empty string")
    n = 0
    for c in s:
        idx = _B58_ALPHABET.index(c)  # 不在表里抛 ValueError
        n = n * 58 + idx

    # 大整数转 bytes（大端）
    nbytes = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""

    # 前导零字节恢复：base58 里每个前导 '1' 对应原始 payload 的一个 \x00
    leading_zeros = 0
    for c in s:
        if c == "1":
            leading_zeros += 1
        else:
            break
    full = b"\x00" * leading_zeros + nbytes

    if len(full) < 4:
        raise ValueError("base58check: data too short")

    payload, checksum = full[:-4], full[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if expected != checksum:
        raise ValueError("base58check: checksum mismatch")
    return payload


# ---------------- 地址辅助 ----------------


def _normalize_addr(addr: str) -> str:
    """把 Tron 地址统一规整成 hex 形态（41 + 20B 共 42 字符，全小写）。

    支持：
    - base58 (T... 长度 34)：base58check decode → 21B → hex (42 字符，0x41 开头)
    - hex 41xxx... 42 字符：直接 lower
    - 0x41xxx... 44 字符：去掉 0x 后 lower
    - 其他形态：lower 原样返回（让上层比较失败即可）
    """
    if not addr:
        return ""
    s = addr.strip()

    # base58 形态：T 开头 34 长
    if len(s) == 34 and s.startswith("T"):
        try:
            payload = _b58decode_check(s)
            return payload.hex().lower()
        except ValueError:
            return s.lower()

    # hex 形态
    if s.lower().startswith("0x"):
        s = s[2:]
    return s.lower()


def _addr_match(a: str | None, b: str | None) -> bool:
    """比较两个 Tron 地址（兼容 base58/hex），相同地址返回 True。"""
    if not a or not b:
        return False
    return _normalize_addr(a) == _normalize_addr(b)


# ---------------- TRC20 transfer data 解析 ----------------


def _parse_trc20_transfer(data_hex: str) -> tuple[str, int] | None:
    """从 transfer(address,uint256) 调用 data 解析 (to_addr_hex_with_41_prefix, amount_raw)。

    data_hex 示例（去掉 0x 前缀）：
        a9059cbb
        000000000000000000000000<addr_20B_hex>
        0000000000000000000000000000000000000000000000000000000000000064

    method_id 必须是 a9059cbb；不是则返回 None。
    body 必须 ≥ 128 hex chars（2 个 32B 参数）；不足返回 None。
    返回的地址带 41 前缀（共 42 hex 字符），与 TronGrid 其他地方 hex 形态一致。
    """
    if not data_hex:
        return None
    s = data_hex.lower()
    if s.startswith("0x"):
        s = s[2:]

    # method id 8 hex
    if len(s) < 8 or s[:8] != TRC20_TRANSFER_METHOD_ID:
        return None
    body = s[8:]
    if len(body) < 128:
        return None

    # 第一个 32B 参数：address，左侧 12B 0 填充，后 20B 是地址
    addr_word = body[:64]
    addr_20b_hex = addr_word[24:]  # 后 40 hex chars = 20 bytes
    to_addr_hex = "41" + addr_20b_hex  # 加上 Tron 主网前缀

    # 第二个 32B 参数：uint256 amount
    amount_word = body[64:128]
    try:
        amount_raw = int(amount_word, 16)
    except ValueError:
        return None

    return to_addr_hex, amount_raw


# ---------------- 主入口 ----------------


def _expected_contract(network: str) -> str:
    return USDT_CONTRACT_MAINNET if network == "mainnet" else USDT_CONTRACT_SHASTA


def verify_tx(
    tron: TronClient,
    network: str,
    tx_hash: str,
    expected_to: str,
    expected_from: str,
    min_amount_usdt: Decimal,
    expires_at: datetime,
    confirmations_required: int = 19,
) -> VerifyResult:
    """7 项链上校验。任一失败立即返回，不继续。

    expires_at 必须为 naive UTC datetime（与 T2 写入的 ``datetime.utcnow() + 24h`` 同
    形态）；本函数内部把 blockTimeStamp 也归一为 naive UTC 后再比较。

    可能抛 ``httpx.HTTPError`` / ``httpx.RequestError``（链上 RPC 故障）。
    调用方（T4 submit handler）需捕获并映射成 503 / TRON_RPC_ERROR 响应。
    """

    # 1. 交易存在
    info = tron.get_transaction_info(tx_hash)
    if not info or not info.get("id"):
        return VerifyResult(False, "TX_NOT_FOUND", "交易未找到或尚未上链")

    # 2. 执行成功
    receipt = info.get("receipt") or {}
    if receipt.get("result") != "SUCCESS":
        return VerifyResult(False, "TX_NOT_SUCCESS", "交易执行未成功")

    # 3. 合约地址匹配
    expected_contract = _expected_contract(network)
    if not _addr_match(info.get("contract_address"), expected_contract):
        return VerifyResult(False, "WRONG_CONTRACT", "合约地址不是 USDT-TRC20")

    # 4. method/to/from 校验（解析 raw transaction）
    tx = tron.get_transaction(tx_hash)
    contract_value: dict[str, Any] | None = None
    try:
        contracts = tx["raw_data"]["contract"]
        if contracts:
            contract_value = contracts[0]["parameter"]["value"]
    except (KeyError, TypeError, IndexError):
        contract_value = None

    if not contract_value:
        return VerifyResult(False, "WRONG_METHOD", "交易体结构异常或非 transfer 调用")

    data_hex = contract_value.get("data") or ""
    parsed = _parse_trc20_transfer(data_hex)
    if parsed is None:
        return VerifyResult(False, "WRONG_METHOD", "非 TRC20 transfer 调用")
    to_addr_hex, raw_amount = parsed

    if not _addr_match(to_addr_hex, expected_to):
        return VerifyResult(False, "WRONG_TO", "收款地址与订单不匹配")

    owner_address = contract_value.get("owner_address")
    if not _addr_match(owner_address, expected_from):
        return VerifyResult(False, "WRONG_FROM", "转出地址与订单声明不匹配")

    # 5. 金额校验
    tx_amount = Decimal(raw_amount) / Decimal(10**USDT_DECIMALS)
    if tx_amount < min_amount_usdt:
        return VerifyResult(
            False,
            "AMOUNT_INSUFFICIENT",
            f"实际转账 {tx_amount} USDT 低于订单 {min_amount_usdt}",
        )

    # 6. 确认数
    block_number = info.get("blockNumber")
    if block_number is None:
        return VerifyResult(False, "NOT_ENOUGH_CONFIRMATIONS", "交易尚未打包入块")
    now_block = tron.get_now_block_number()
    if (now_block - int(block_number)) < confirmations_required:
        return VerifyResult(
            False,
            "NOT_ENOUGH_CONFIRMATIONS",
            f"确认数不足（需 {confirmations_required}）",
        )

    # 7. 时效（TronGrid blockTimeStamp 是 UTC 毫秒；归一为 naive UTC 与 expires_at 比较）
    block_ts_ms = info.get("blockTimeStamp")
    if block_ts_ms is not None:
        block_ts = datetime.fromtimestamp(
            int(block_ts_ms) / 1000, tz=timezone.utc
        ).replace(tzinfo=None)
        if block_ts > expires_at:
            return VerifyResult(False, "TX_AFTER_EXPIRY", "交易时间晚于订单过期时刻")

    return VerifyResult(True, "OK", "", tx_amount)
