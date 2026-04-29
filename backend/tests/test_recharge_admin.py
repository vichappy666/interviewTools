"""End-to-end tests for /api/admin/recharge/* (M3 T5)。

verify_tx 不会被调用（admin endpoint 全是手动操作），broadcast mock 掉。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app import configs as configs_module
from app.auth.security import hash_password, make_admin_token, make_user_token
from app.models.admin import Admin
from app.models.admin_audit_log import AdminAuditLog
from app.models.balance_ledger import BalanceLedger
from app.models.recharge_order import RechargeOrder
from app.models.user import User
import app.recharge.admin_router as admin_router_mod


VALID_FROM = "TUserAddrAAAAAAAAAAAAAAAAAAAAAAAAA"  # 34 chars
PLATFORM_TO = "TPlatformAddrBBBBBBBBBBBBBBBBBBBBB"  # 34 chars


@pytest.fixture(autouse=True)
def _reset_configs_cache():
    configs_module._cache.clear()
    configs_module._cache["recharge.to_address"] = PLATFORM_TO
    configs_module._cache["recharge.rate_per_usdt"] = 60
    configs_module._cache["recharge.network"] = "shasta"
    yield
    configs_module._cache.clear()


@pytest.fixture(autouse=True)
def _mute_broadcast(monkeypatch):
    """force_success 末尾会调 broadcast；测试里默默吞掉，单独的测试可以再 monkeypatch。"""
    async def _noop(user_id, balance):  # noqa: ARG001
        return None
    monkeypatch.setattr(admin_router_mod, "_broadcast_balance_to_user", _noop)


def _make_admin(db, username="admin", password="admin"):
    a = Admin(username=username, password_hash=hash_password(password))
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_user(db, username="alice", balance=0):
    u = User(
        username=username,
        password_hash=hash_password("secret123"),
        balance_seconds=balance,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _admin_headers(admin_id: int) -> dict:
    return {"Authorization": f"Bearer {make_admin_token(admin_id)}"}


def _user_headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {make_user_token(user_id)}"}


def _make_order(
    db,
    user_id: int,
    *,
    amount: str = "50",
    status: str = "pending",
    rate_per_usdt: int = 60,
    tx_hash: str | None = None,
    tx_amount_usdt: str | None = None,
    granted_seconds: int | None = None,
    fail_reason: str | None = None,
    succeeded_at: datetime | None = None,
    expires_at: datetime | None = None,
    created_at: datetime | None = None,
) -> RechargeOrder:
    o = RechargeOrder(
        user_id=user_id,
        amount_usdt=Decimal(amount),
        from_address=VALID_FROM,
        to_address=PLATFORM_TO,
        tx_hash=tx_hash,
        tx_amount_usdt=Decimal(tx_amount_usdt) if tx_amount_usdt else None,
        granted_seconds=granted_seconds,
        rate_per_usdt=rate_per_usdt,
        status=status,
        fail_reason=fail_reason,
        succeeded_at=succeeded_at,
        expires_at=expires_at or (datetime.utcnow() + timedelta(hours=24)),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    if created_at is not None:
        # 直接覆盖 created_at（server_default 不可控）
        o.created_at = created_at
        db.commit()
        db.refresh(o)
    return o


# ---------------- list ----------------

def test_list_all_orders_admin(client, db_session):
    a = _make_admin(db_session)
    u1 = _make_user(db_session, username="alice")
    u2 = _make_user(db_session, username="bob")
    _make_order(db_session, u1.id, amount="50", status="pending")
    _make_order(db_session, u2.id, amount="20", status="succeeded")
    _make_order(db_session, u2.id, amount="30", status="failed")

    r = client.get("/api/admin/recharge/orders", headers=_admin_headers(a.id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    usernames = {item["username"] for item in body["items"]}
    assert usernames == {"alice", "bob"}


def test_list_filter_by_status(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session)
    _make_order(db_session, u.id, status="pending")
    _make_order(db_session, u.id, status="pending")
    _make_order(db_session, u.id, status="succeeded")

    r = client.get(
        "/api/admin/recharge/orders?status=pending", headers=_admin_headers(a.id)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert all(item["status"] == "pending" for item in body["items"])


def test_list_filter_by_user_id(client, db_session):
    a = _make_admin(db_session)
    u1 = _make_user(db_session, username="alice")
    u2 = _make_user(db_session, username="bob")
    _make_order(db_session, u1.id)
    _make_order(db_session, u1.id)
    _make_order(db_session, u2.id)

    r = client.get(
        f"/api/admin/recharge/orders?user_id={u2.id}", headers=_admin_headers(a.id)
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["user_id"] == u2.id
    assert body["items"][0]["username"] == "bob"


# ---------------- force-success ----------------

def test_force_success_increments_balance(client, db_session, monkeypatch):
    a = _make_admin(db_session)
    u = _make_user(db_session, balance=100)
    o = _make_order(db_session, u.id, amount="50", rate_per_usdt=60, status="pending")

    calls = []

    async def fake_broadcast(user_id, balance):
        calls.append((user_id, balance))

    monkeypatch.setattr(admin_router_mod, "_broadcast_balance_to_user", fake_broadcast)

    r = client.post(
        f"/api/admin/recharge/orders/{o.id}/force-success",
        headers=_admin_headers(a.id),
        json={"note": "manual"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["granted_seconds"] == 3000  # 50 × 60
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
    assert ledgers[0].delta_seconds == 3000
    assert ledgers[0].ref_id == o.id
    assert "admin force" in (ledgers[0].note or "")

    # broadcast 被调用一次（commit 之后）
    assert calls == [(u.id, 3100)]


def test_force_success_writes_audit(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session)
    o = _make_order(db_session, u.id, amount="20", status="failed")

    r = client.post(
        f"/api/admin/recharge/orders/{o.id}/force-success",
        headers=_admin_headers(a.id),
        json={"note": "客服手动核销"},
    )
    assert r.status_code == 200, r.text

    rows = (
        db_session.query(AdminAuditLog)
        .filter(AdminAuditLog.action == "force_recharge_success")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].admin_id == a.id
    assert rows[0].target_type == "recharge_order"
    assert rows[0].target_id == str(o.id)
    assert rows[0].note == "客服手动核销"
    assert rows[0].payload["granted_seconds"] == 1200  # 20 × 60


def test_force_success_rejects_already_succeeded(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session)
    o = _make_order(db_session, u.id, status="succeeded")

    r = client.post(
        f"/api/admin/recharge/orders/{o.id}/force-success",
        headers=_admin_headers(a.id),
        json={"note": "x"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "ORDER_NOT_FORCEABLE"


# ---------------- force-fail ----------------

def test_force_fail_writes_audit(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session, balance=10)
    o = _make_order(db_session, u.id, status="pending")

    r = client.post(
        f"/api/admin/recharge/orders/{o.id}/force-fail",
        headers=_admin_headers(a.id),
        json={"note": "用户未付款"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert "用户未付款" in (body["fail_reason"] or "")

    db_session.expire_all()
    order = db_session.get(RechargeOrder, o.id)
    assert order.status == "failed"
    assert "admin force" in (order.fail_reason or "")
    # 余额不变
    assert db_session.get(User, u.id).balance_seconds == 10

    rows = (
        db_session.query(AdminAuditLog)
        .filter(AdminAuditLog.action == "force_recharge_fail")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].target_id == str(o.id)
    assert rows[0].note == "用户未付款"


def test_force_fail_rejects_succeeded(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session)
    o = _make_order(db_session, u.id, status="succeeded")

    r = client.post(
        f"/api/admin/recharge/orders/{o.id}/force-fail",
        headers=_admin_headers(a.id),
        json={"note": "x"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "ORDER_NOT_FORCEABLE"


# ---------------- retry ----------------

def test_retry_resets_to_pending(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session)
    o = _make_order(
        db_session,
        u.id,
        status="failed",
        tx_hash="a" * 64,
        fail_reason="WRONG_FROM: 转出地址不匹配",
    )

    r = client.post(
        f"/api/admin/recharge/orders/{o.id}/retry",
        headers=_admin_headers(a.id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["tx_hash"] is None
    assert body["fail_reason"] is None

    db_session.expire_all()
    order = db_session.get(RechargeOrder, o.id)
    assert order.status == "pending"
    assert order.tx_hash is None
    assert order.fail_reason is None

    rows = (
        db_session.query(AdminAuditLog)
        .filter(AdminAuditLog.action == "retry_recharge_order")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].target_id == str(o.id)


def test_retry_rejects_pending(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session)
    o = _make_order(db_session, u.id, status="pending")

    r = client.post(
        f"/api/admin/recharge/orders/{o.id}/retry",
        headers=_admin_headers(a.id),
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "ORDER_NOT_FORCEABLE"


# ---------------- auth isolation ----------------

def test_non_admin_token_rejected(client, db_session):
    u = _make_user(db_session)
    r = client.get("/api/admin/recharge/orders", headers=_user_headers(u.id))
    assert r.status_code == 401
