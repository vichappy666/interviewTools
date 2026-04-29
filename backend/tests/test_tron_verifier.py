"""M3 T3 链上校验器单测。

全部 mock TronClient，不发任何真实网络请求；T10 端到端会再在 Shasta 跑。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.recharge.tron import TronClient
from app.recharge.verifier import (
    USDT_CONTRACT_MAINNET,
    _addr_match,
    _b58decode_check,
    _normalize_addr,
    _parse_trc20_transfer,
    verify_tx,
)


# --------- 测试常量（用合法 base58check 真实地址） ----------

# USDT-TRC20 主网合约地址
CONTRACT_BASE58 = USDT_CONTRACT_MAINNET  # "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
CONTRACT_HEX = "41a614f803b6fd780986a42c78ec9c7f77e6ded13c"

# 几个公开真实 base58 地址用于 to/from（仅用作字符串测试，不会发交易）
ADDR_TO_BASE58 = "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7"  # 一个常见 TRC20 地址
ADDR_FROM_BASE58 = "TJRabPrwbZy45sbavfcjinPJC18kjpRTv8"


def _b58_to_hex(addr_b58: str) -> str:
    return _b58decode_check(addr_b58).hex().lower()


# --------- helpers：构造 transfer data / contract param / mock ---------


def _make_transfer_data(to_hex_no_41: str, amount: int) -> str:
    """构造合法的 TRC20 transfer(address,uint256) 调用 data hex。

    to_hex_no_41 是 20 字节地址 hex（不含 41 前缀，40 chars）。
    """
    assert len(to_hex_no_41) == 40, "to address must be 20-byte hex"
    addr_word = "0" * 24 + to_hex_no_41  # 12B 0 padding + 20B addr
    amount_word = format(amount, "064x")
    return "a9059cbb" + addr_word + amount_word


def _make_contract_param(
    owner_hex_with_41: str, contract_hex_with_41: str, data_hex: str
) -> dict:
    return {
        "owner_address": owner_hex_with_41,
        "contract_address": contract_hex_with_41,
        "data": data_hex,
    }


def _make_tx(owner_hex: str, contract_hex: str, data_hex: str) -> dict:
    return {
        "txID": "deadbeef",
        "raw_data": {
            "contract": [
                {
                    "type": "TriggerSmartContract",
                    "parameter": {
                        "value": _make_contract_param(
                            owner_hex, contract_hex, data_hex
                        ),
                    },
                }
            ],
        },
    }


def _make_info(
    *,
    block_number: int = 1000,
    block_ts_ms: int | None = None,
    contract_addr_hex: str = CONTRACT_HEX,
    receipt_result: str = "SUCCESS",
    has_id: bool = True,
) -> dict:
    if block_ts_ms is None:
        block_ts_ms = int(datetime.utcnow().timestamp() * 1000)
    info: dict = {
        "blockNumber": block_number,
        "blockTimeStamp": block_ts_ms,
        "contract_address": contract_addr_hex,
        "receipt": {"result": receipt_result},
    }
    if has_id:
        info["id"] = "deadbeef"
    return info


def make_mock_tron(info: dict, tx: dict, now_block: int) -> MagicMock:
    m = MagicMock(spec=TronClient)
    m.get_transaction_info.return_value = info
    m.get_transaction.return_value = tx
    m.get_now_block_number.return_value = now_block
    return m


# --------- happy-path fixture ---------


def _happy_setup(
    *,
    raw_amount: int = 50_000_000,  # 50 USDT
    block_number: int = 1000,
    now_block: int = 1019,  # 19 confirmations
    block_ts_ms: int | None = None,
    contract_addr_hex: str = CONTRACT_HEX,
    receipt_result: str = "SUCCESS",
    has_id: bool = True,
    to_b58: str = ADDR_TO_BASE58,
    from_b58: str = ADDR_FROM_BASE58,
    method_id: str = "a9059cbb",
):
    to_hex_full = _b58_to_hex(to_b58)
    from_hex_full = _b58_to_hex(from_b58)
    to_hex_no41 = to_hex_full[2:]  # 去掉 41 前缀

    data = method_id + _make_transfer_data(to_hex_no41, raw_amount)[8:]
    info = _make_info(
        block_number=block_number,
        block_ts_ms=block_ts_ms,
        contract_addr_hex=contract_addr_hex,
        receipt_result=receipt_result,
        has_id=has_id,
    )
    tx = _make_tx(from_hex_full, contract_addr_hex, data)
    tron = make_mock_tron(info, tx, now_block)
    return tron, to_b58, from_b58


# ============================================================
# 1. 完整 happy path
# ============================================================


def test_verify_success():
    tron, to_b58, from_b58 = _happy_setup()
    expires_at = datetime.utcnow() + timedelta(hours=24)
    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="deadbeef",
        expected_to=to_b58,
        expected_from=from_b58,
        min_amount_usdt=Decimal("10"),
        expires_at=expires_at,
        confirmations_required=19,
    )
    assert res.ok is True
    assert res.code == "OK"
    assert res.tx_amount_usdt == Decimal("50.000000")


# ============================================================
# 2. tx 不存在
# ============================================================


def test_tx_not_found():
    tron = make_mock_tron({}, {}, 1000)
    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="x",
        expected_to=ADDR_TO_BASE58,
        expected_from=ADDR_FROM_BASE58,
        min_amount_usdt=Decimal("1"),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert res.ok is False
    assert res.code == "TX_NOT_FOUND"


# ============================================================
# 3. 执行失败
# ============================================================


def test_tx_not_success():
    tron, to_b58, from_b58 = _happy_setup(receipt_result="FAILED")
    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="x",
        expected_to=to_b58,
        expected_from=from_b58,
        min_amount_usdt=Decimal("1"),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert res.ok is False
    assert res.code == "TX_NOT_SUCCESS"


# ============================================================
# 4. 合约不对
# ============================================================


def test_wrong_contract():
    # 用一个完全不同的合约 hex
    other_hex = "41" + "00" * 20
    tron, to_b58, from_b58 = _happy_setup(contract_addr_hex=other_hex)
    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="x",
        expected_to=to_b58,
        expected_from=from_b58,
        min_amount_usdt=Decimal("1"),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert res.ok is False
    assert res.code == "WRONG_CONTRACT"


# ============================================================
# 5. method 不对（不是 a9059cbb 开头）
# ============================================================


def test_wrong_method():
    # 用 happy_setup 但把 method_id 换掉
    to_hex_full = _b58_to_hex(ADDR_TO_BASE58)
    from_hex_full = _b58_to_hex(ADDR_FROM_BASE58)
    to_hex_no41 = to_hex_full[2:]

    fake_method = "ffffffff"
    body = _make_transfer_data(to_hex_no41, 50_000_000)[8:]
    data = fake_method + body
    info = _make_info()
    tx = _make_tx(from_hex_full, CONTRACT_HEX, data)
    tron = make_mock_tron(info, tx, 1019)

    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="x",
        expected_to=ADDR_TO_BASE58,
        expected_from=ADDR_FROM_BASE58,
        min_amount_usdt=Decimal("1"),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert res.ok is False
    assert res.code == "WRONG_METHOD"


# ============================================================
# 6. to 不对
# ============================================================


def test_wrong_to():
    # data 里的 to 是 ADDR_TO_BASE58；但我们传 expected_to = ADDR_FROM_BASE58
    tron, _, from_b58 = _happy_setup()
    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="x",
        expected_to=ADDR_FROM_BASE58,  # 不是 data 里的 to
        expected_from=from_b58,
        min_amount_usdt=Decimal("1"),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert res.ok is False
    assert res.code == "WRONG_TO"


# ============================================================
# 7. from 不对（防 hash 偷盗的核心）
# ============================================================


def test_wrong_from():
    tron, to_b58, _ = _happy_setup()
    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="x",
        expected_to=to_b58,
        expected_from=ADDR_TO_BASE58,  # 故意写错 from
        min_amount_usdt=Decimal("1"),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert res.ok is False
    assert res.code == "WRONG_FROM"


# ============================================================
# 8. 金额不足
# ============================================================


def test_amount_insufficient():
    # raw_amount = 9.999999 USDT；min = 10 USDT
    tron, to_b58, from_b58 = _happy_setup(raw_amount=9_999_999)
    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="x",
        expected_to=to_b58,
        expected_from=from_b58,
        min_amount_usdt=Decimal("10"),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert res.ok is False
    assert res.code == "AMOUNT_INSUFFICIENT"


# ============================================================
# 9. 金额恰好相等（边界）
# ============================================================


def test_amount_exact_match():
    tron, to_b58, from_b58 = _happy_setup(raw_amount=10_000_000)  # 正好 10 USDT
    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="x",
        expected_to=to_b58,
        expected_from=from_b58,
        min_amount_usdt=Decimal("10"),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    assert res.ok is True
    assert res.tx_amount_usdt == Decimal("10.000000")


# ============================================================
# 10. 确认数不足
# ============================================================


def test_not_enough_confirmations():
    # block_number=100, now_block=110, required=19 → diff=10
    tron, to_b58, from_b58 = _happy_setup(block_number=100, now_block=110)
    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="x",
        expected_to=to_b58,
        expected_from=from_b58,
        min_amount_usdt=Decimal("1"),
        expires_at=datetime.utcnow() + timedelta(hours=1),
        confirmations_required=19,
    )
    assert res.ok is False
    assert res.code == "NOT_ENOUGH_CONFIRMATIONS"


# ============================================================
# 11. 时间晚于过期
# ============================================================


def test_tx_after_expiry():
    # block 时间设为 1 小时后
    future_ts_ms = int((datetime.utcnow() + timedelta(hours=1)).timestamp() * 1000)
    tron, to_b58, from_b58 = _happy_setup(block_ts_ms=future_ts_ms)
    expires_at = datetime.utcnow()  # 已过期
    res = verify_tx(
        tron,
        network="mainnet",
        tx_hash="x",
        expected_to=to_b58,
        expected_from=from_b58,
        min_amount_usdt=Decimal("1"),
        expires_at=expires_at,
    )
    assert res.ok is False
    assert res.code == "TX_AFTER_EXPIRY"


# ============================================================
# 12. _addr_match: base58 vs hex 视为相等
# ============================================================


def test_addr_match_base58_vs_hex():
    # 真实 USDT-TRC20 base58 ↔ 已知 hex
    assert _addr_match(USDT_CONTRACT_MAINNET, CONTRACT_HEX) is True
    assert _addr_match(CONTRACT_HEX, USDT_CONTRACT_MAINNET) is True
    # 大小写忽略
    assert _addr_match(USDT_CONTRACT_MAINNET, CONTRACT_HEX.upper()) is True
    # 不同地址不相等
    assert _addr_match(USDT_CONTRACT_MAINNET, "41" + "00" * 20) is False
    # 任意一边空
    assert _addr_match(None, CONTRACT_HEX) is False
    assert _addr_match(USDT_CONTRACT_MAINNET, "") is False


# ============================================================
# 13. base58check checksum 失败必须抛
# ============================================================


def test_b58decode_check_invalid_checksum():
    # 改最后一个字符（破坏 checksum）
    bad = USDT_CONTRACT_MAINNET[:-1] + ("u" if USDT_CONTRACT_MAINNET[-1] != "u" else "v")
    with pytest.raises(ValueError):
        _b58decode_check(bad)


# ============================================================
# 额外：parser & normalize 单元测试
# ============================================================


def test_parse_trc20_transfer_basic():
    to_hex_no41 = "a614f803b6fd780986a42c78ec9c7f77e6ded13c"
    data = _make_transfer_data(to_hex_no41, 12345)
    out = _parse_trc20_transfer(data)
    assert out is not None
    to_addr, amount = out
    assert to_addr == "41" + to_hex_no41
    assert amount == 12345


def test_parse_trc20_transfer_wrong_method():
    data = "deadbeef" + "0" * 128
    assert _parse_trc20_transfer(data) is None


def test_parse_trc20_transfer_too_short():
    assert _parse_trc20_transfer("a9059cbb") is None
    assert _parse_trc20_transfer("") is None


def test_normalize_addr_forms():
    hex_form = _normalize_addr(USDT_CONTRACT_MAINNET)
    assert hex_form == CONTRACT_HEX
    assert _normalize_addr(CONTRACT_HEX) == CONTRACT_HEX
    assert _normalize_addr(CONTRACT_HEX.upper()) == CONTRACT_HEX
    assert _normalize_addr("0x" + CONTRACT_HEX) == CONTRACT_HEX
