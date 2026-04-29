"""End-to-end tests for POST /api/recharge/orders/{id}/submit (M3 T4)。

verify_tx 全 mock；不发链上请求。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app import configs as configs_module
from app.auth.security import hash_password, make_user_token
from app.models.balance_ledger import BalanceLedger
from app.models.recharge_order import RechargeOrder
from app.models.user import User
import app.recharge.router as router_mod
from app.recharge.verifier import VerifyResult


VALID_FROM = "TUserAddrAAAAAAAAAAAAAAAAAAAAAAAAA"  # 34 chars
PLATFORM_TO = "TPlatformAddrBBBBBBBBBBBBBBBBBBBBB"  # 34 chars
HASH_A = "a" * 64
HASH_B = "b" * 64


def _make_user(db, username="alice", password="secret123", balance=0):
    u = User(
        username=username,
        password_hash=hash_password(password),
        balance_seconds=balance,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth_headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {make_user_token(user_id)}"}


def _create_pending_order(
    client, user_id, amount="50", from_address=VALID_FROM
):
    r = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(user_id),
        json={"amount_usdt": amount, "from_address": from_address},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(autouse=True)
def _reset_configs_cache():
    configs_module._cache.clear()
    configs_module._cache["recharge.to_address"] = PLATFORM_TO
    configs_module._cache["recharge.rate_per_usdt"] = 60
    configs_module._cache["recharge.network"] = "shasta"
    yield
    configs_module._cache.clear()


@pytest.fixture
def fake_tron(monkeypatch):
    """Patch TronClient → no-op，verify_tx 也由本测试 mock。"""
    class _FakeClient:
        def __init__(self, *a, **kw):
            pass
        def close(self):
            pass
    monkeypatch.setattr(router_mod, "TronClient", _FakeClient)
    return _FakeClient


def _set_verify(monkeypatch, fn):
    monkeypatch.setattr(router_mod, "verify_tx", fn)


# ---------------- 1. 成功 ----------------

def test_submit_success(client, db_session, fake_tron, monkeypatch):
    u = _make_user(db_session, balance=100)
    o = _create_pending_order(client, u.id, amount="50")

    def ok(*a, **kw):
        return VerifyResult(True, "OK", "", Decimal("50"))
    _set_verify(monkeypatch, ok)

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["tx_hash"] == HASH_A
    assert body["granted_seconds"] == 3000  # 50 USDT * rate 60
    assert Decimal(body["tx_amount_usdt"]) == Decimal("50")
    assert body["succeeded_at"] is not None

    db_session.expire_all()
    user = db_session.get(User, u.id)
    assert user.balance_seconds == 100 + 3000

    ledgers = (
        db_session.query(BalanceLedger)
        .filter(BalanceLedger.user_id == u.id, BalanceLedger.reason == "recharge")
        .all()
    )
    assert len(ledgers) == 1
    led = ledgers[0]
    assert led.delta_seconds == 3000
    assert led.ref_type == "recharge"
    assert led.ref_id == o["id"]
    assert led.balance_after == 3100


# ---------------- 2-3. 鉴权 / 不存在 ----------------

def test_submit_order_not_found(client, db_session, fake_tron):
    u = _make_user(db_session)
    r = client.post(
        "/api/recharge/orders/99999/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error"]["code"] == "ORDER_NOT_FOUND"


def test_submit_order_other_user(client, db_session, fake_tron):
    a = _make_user(db_session, username="alice")
    b = _make_user(db_session, username="bob")
    o = _create_pending_order(client, a.id, amount="50")

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(b.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error"]["code"] == "ORDER_NOT_FOUND"


# ---------------- 4. status != pending ----------------

def test_submit_already_succeeded(client, db_session, fake_tron):
    u = _make_user(db_session)
    o = _create_pending_order(client, u.id, amount="50")
    # 直接改 DB
    order = db_session.get(RechargeOrder, o["id"])
    order.status = "succeeded"
    db_session.commit()

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "ORDER_NOT_PENDING"
    assert "succeeded" in r.json()["detail"]["error"]["message"]


# ---------------- 5. expired ----------------

def test_submit_expired_order(client, db_session, fake_tron):
    u = _make_user(db_session)
    o = _create_pending_order(client, u.id, amount="50")

    order = db_session.get(RechargeOrder, o["id"])
    order.expires_at = datetime.utcnow() - timedelta(hours=1)
    db_session.commit()

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "ORDER_EXPIRED"

    db_session.expire_all()
    order2 = db_session.get(RechargeOrder, o["id"])
    assert order2.status == "expired"


# ---------------- 6. 非法 hash ----------------

@pytest.mark.parametrize(
    "bad_hash",
    [
        "abc",            # 太短
        "",               # 空
        "z" * 64,         # 含非 hex
        "a" * 63,         # 长度差 1
        "a" * 65,         # 长 1
        "0x" + "a" * 63,  # 0x 前缀但长度仍然不对
    ],
)
def test_submit_invalid_tx_hash(client, db_session, fake_tron, monkeypatch, bad_hash):
    u = _make_user(db_session)
    o = _create_pending_order(client, u.id, amount="50")

    called = {"v": False}
    def should_not_be_called(*a, **kw):
        called["v"] = True
        return VerifyResult(True, "OK", "", Decimal("50"))
    _set_verify(monkeypatch, should_not_be_called)

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": bad_hash},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"]["code"] == "INVALID_TX_HASH"
    assert called["v"] is False  # verify_tx 不被调用


# ---------------- 7. hash 已被使用 ----------------

def test_submit_hash_already_used(client, db_session, fake_tron, monkeypatch):
    u = _make_user(db_session, balance=0)
    o_a = _create_pending_order(client, u.id, amount="50")
    o_b = _create_pending_order(client, u.id, amount="50")

    def ok(*a, **kw):
        return VerifyResult(True, "OK", "", Decimal("50"))
    _set_verify(monkeypatch, ok)

    # 先用 HASH_A 提交订单 A → 成功
    r1 = client.post(
        f"/api/recharge/orders/{o_a['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r1.status_code == 200, r1.text

    # 再用 HASH_A 提交订单 B → 应 400 HASH_ALREADY_USED
    r2 = client.post(
        f"/api/recharge/orders/{o_b['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r2.status_code == 400
    assert r2.json()["detail"]["error"]["code"] == "HASH_ALREADY_USED"

    # 订单 B 在 DB 里应该还是 pending（IntegrityError 后 rollback）
    db_session.expire_all()
    order_b = db_session.get(RechargeOrder, o_b["id"])
    assert order_b.status == "pending"
    assert order_b.tx_hash is None


# ---------------- 8. verify failed: WRONG_FROM ----------------

def test_submit_verify_failed_wrong_from(client, db_session, fake_tron, monkeypatch):
    u = _make_user(db_session, balance=10)
    o = _create_pending_order(client, u.id, amount="50")

    def fail(*a, **kw):
        return VerifyResult(False, "WRONG_FROM", "转出地址不匹配")
    _set_verify(monkeypatch, fail)

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "WRONG_FROM"

    db_session.expire_all()
    order = db_session.get(RechargeOrder, o["id"])
    assert order.status == "failed"
    assert "WRONG_FROM" in (order.fail_reason or "")

    # 余额没变
    user = db_session.get(User, u.id)
    assert user.balance_seconds == 10


# ---------------- 9. verify failed: AMOUNT_INSUFFICIENT ----------------

def test_submit_verify_failed_amount(client, db_session, fake_tron, monkeypatch):
    u = _make_user(db_session)
    o = _create_pending_order(client, u.id, amount="50")

    def fail(*a, **kw):
        return VerifyResult(False, "AMOUNT_INSUFFICIENT", "实际金额过低")
    _set_verify(monkeypatch, fail)

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "AMOUNT_INSUFFICIENT"

    db_session.expire_all()
    order = db_session.get(RechargeOrder, o["id"])
    assert order.status == "failed"


# ---------------- 10. amount floor (Decimal × int) ----------------

def test_submit_amount_floor(client, db_session, fake_tron, monkeypatch):
    """tx_amount=50.5, rate=60 → granted = int(50.5 * 60) = 3030."""
    u = _make_user(db_session, balance=0)
    o = _create_pending_order(client, u.id, amount="50")

    def ok(*a, **kw):
        return VerifyResult(True, "OK", "", Decimal("50.5"))
    _set_verify(monkeypatch, ok)

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 200, r.text
    assert r.json()["granted_seconds"] == 3030

    db_session.expire_all()
    user = db_session.get(User, u.id)
    assert user.balance_seconds == 3030


# ---------------- 11. RPC error → 503 ----------------

def test_submit_rpc_error(client, db_session, fake_tron, monkeypatch):
    """网络错（ConnectError / RequestError）→ 503 TRON_RPC_ERROR。"""
    u = _make_user(db_session)
    o = _create_pending_order(client, u.id, amount="50")

    def boom(*a, **kw):
        raise httpx.ConnectError("boom")
    _set_verify(monkeypatch, boom)

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"]["code"] == "TRON_RPC_ERROR"

    db_session.expire_all()
    order = db_session.get(RechargeOrder, o["id"])
    assert order.status == "failed"
    assert "RPC" in (order.fail_reason or "") or "boom" in (order.fail_reason or "")


def test_submit_rpc_5xx_status_error(client, db_session, fake_tron, monkeypatch):
    """TronGrid 返回 502 → 503 TRON_RPC_ERROR（视作可重试）。"""
    u = _make_user(db_session)
    o = _create_pending_order(client, u.id, amount="50")

    def boom_502(*a, **kw):
        req = httpx.Request("POST", "https://api.shasta.trongrid.io/x")
        resp = httpx.Response(502, request=req)
        raise httpx.HTTPStatusError("upstream", request=req, response=resp)
    _set_verify(monkeypatch, boom_502)

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"]["code"] == "TRON_RPC_ERROR"
    db_session.expire_all()
    assert db_session.get(RechargeOrder, o["id"]).status == "failed"


def test_submit_rpc_4xx_status_error(client, db_session, fake_tron, monkeypatch):
    """TronGrid 返回 400 → 500 TRON_RPC_BAD_REQUEST（多半是配置/请求构造问题）。"""
    u = _make_user(db_session)
    o = _create_pending_order(client, u.id, amount="50")

    def boom_400(*a, **kw):
        req = httpx.Request("POST", "https://api.shasta.trongrid.io/x")
        resp = httpx.Response(400, request=req)
        raise httpx.HTTPStatusError("bad request", request=req, response=resp)
    _set_verify(monkeypatch, boom_400)

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 500
    assert r.json()["detail"]["error"]["code"] == "TRON_RPC_BAD_REQUEST"
    db_session.expire_all()
    order = db_session.get(RechargeOrder, o["id"])
    assert order.status == "failed"
    assert "400" in (order.fail_reason or "")


def test_submit_credit_failure_marks_order_failed(
    client, db_session, fake_tron, monkeypatch
):
    """verify_tx 通过但 credit_recharge 抛异常 → 订单不能停在 verifying，
    必须被回滚到 failed，避免用户看到永久卡住的中间态。"""
    u = _make_user(db_session, balance=100)
    o = _create_pending_order(client, u.id, amount="50")

    def ok(*a, **kw):
        return VerifyResult(True, "OK", "", Decimal("50"))
    _set_verify(monkeypatch, ok)

    def boom_credit(*a, **kw):
        raise RuntimeError("simulated credit failure")
    monkeypatch.setattr(router_mod, "credit_recharge", boom_credit)

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 500
    assert r.json()["detail"]["error"]["code"] == "RECHARGE_INTERNAL_ERROR"

    db_session.expire_all()
    order = db_session.get(RechargeOrder, o["id"])
    assert order.status == "failed"
    assert "simulated credit failure" in (order.fail_reason or "")
    # 余额不变（未入账）
    user = db_session.get(User, u.id)
    assert user.balance_seconds == 100
    # 也没有 ledger 行
    assert db_session.query(BalanceLedger).filter_by(user_id=u.id).count() == 0


# ---------------- 12. broadcast hook ----------------

def test_submit_broadcast_balance(client, db_session, fake_tron, monkeypatch):
    """成功后 broadcast 被调用一次（mock _broadcast_balance_to_user 计数）。"""
    u = _make_user(db_session, balance=0)
    o = _create_pending_order(client, u.id, amount="50")

    def ok(*a, **kw):
        return VerifyResult(True, "OK", "", Decimal("50"))
    _set_verify(monkeypatch, ok)

    calls = []
    async def fake_broadcast(user_id, balance):
        calls.append((user_id, balance))
    monkeypatch.setattr(
        router_mod, "_broadcast_balance_to_user", fake_broadcast
    )

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": HASH_A},
    )
    assert r.status_code == 200, r.text
    assert calls == [(u.id, 3000)]


# ---------------- 13. 0x 前缀 hash 也接受 ----------------

def test_submit_accepts_0x_prefix(client, db_session, fake_tron, monkeypatch):
    u = _make_user(db_session, balance=0)
    o = _create_pending_order(client, u.id, amount="50")

    def ok(*a, **kw):
        return VerifyResult(True, "OK", "", Decimal("50"))
    _set_verify(monkeypatch, ok)

    r = client.post(
        f"/api/recharge/orders/{o['id']}/submit",
        headers=_auth_headers(u.id),
        json={"tx_hash": "0x" + HASH_A},
    )
    assert r.status_code == 200, r.text
    # tx_hash 在 DB 里应该是去掉 0x 的小写形式
    db_session.expire_all()
    order = db_session.get(RechargeOrder, o["id"])
    assert order.tx_hash == HASH_A
