"""End-to-end tests for /api/recharge/* (M3 T2)."""
from decimal import Decimal

import pytest

from app import configs as configs_module
from app.auth.security import hash_password, make_user_token
from app.models.recharge_order import RechargeOrder
from app.models.user import User


# 一个合法的 TRON 地址：T 开头 + 共 34 字符
VALID_FROM = "TUserAddrAAAAAAAAAAAAAAAAAAAAAAAAA"  # 34 chars
PLATFORM_TO = "TPlatformAddrBBBBBBBBBBBBBBBBBBBBB"  # 34 chars


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


@pytest.fixture(autouse=True)
def _reset_configs_cache():
    """每个测试运行前后重置 configs cache，并默认配置好平台收款地址。"""
    configs_module._cache.clear()
    # 默认给一个合法 to_address，避免每个 test 都设置
    configs_module._cache["recharge.to_address"] = PLATFORM_TO
    yield
    configs_module._cache.clear()


# ---------------- POST /orders ----------------

def test_unauthenticated_returns_401(client):
    r = client.post(
        "/api/recharge/orders",
        json={"amount_usdt": "50.000000", "from_address": VALID_FROM},
    )
    assert r.status_code == 401


def test_create_order_success(client, db_session):
    """默认 configs：min=1（默认）、rate=60（默认），to_address 已配。"""
    u = _make_user(db_session)
    r = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "50.000000", "from_address": VALID_FROM},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["user_id"] == u.id
    assert body["amount_usdt"] == "50.000000"
    assert body["from_address"] == VALID_FROM
    assert body["to_address"] == PLATFORM_TO
    assert body["rate_per_usdt"] == 60
    assert body["tx_hash"] is None
    assert body["succeeded_at"] is None
    assert body["expires_at"] is not None

    # DB 中应该有 1 条订单
    rows = (
        db_session.query(RechargeOrder).filter_by(user_id=u.id).all()
    )
    assert len(rows) == 1
    assert rows[0].amount_usdt == Decimal("50.000000")
    assert rows[0].rate_per_usdt == 60


def test_create_order_amount_too_small(client, db_session):
    u = _make_user(db_session)
    r = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "0.5", "from_address": VALID_FROM},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "AMOUNT_TOO_SMALL"
    assert db_session.query(RechargeOrder).filter_by(user_id=u.id).count() == 0


def test_create_order_invalid_amount(client, db_session):
    u = _make_user(db_session)
    r = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "abc", "from_address": VALID_FROM},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "INVALID_AMOUNT"


def test_create_order_invalid_from_address(client, db_session):
    """非 T 开头 / 长度错都视为非法。"""
    u = _make_user(db_session)

    # 非 T 开头
    r1 = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "50", "from_address": "Xabcdefghijklmnopqrstuvwxyz123456"},
    )
    assert r1.status_code == 400
    assert r1.json()["detail"]["error"]["code"] == "INVALID_FROM_ADDRESS"

    # 长度错
    r2 = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "50", "from_address": "Tabc"},
    )
    assert r2.status_code == 400
    assert r2.json()["detail"]["error"]["code"] == "INVALID_FROM_ADDRESS"

    # 空字符串
    r3 = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "50", "from_address": ""},
    )
    assert r3.status_code == 400
    assert r3.json()["detail"]["error"]["code"] == "INVALID_FROM_ADDRESS"


def test_create_order_no_to_address_configured(client, db_session):
    """to_address 缺失 → 400 RECHARGE_NOT_CONFIGURED。"""
    # 清掉 fixture 默认设置的 to_address
    configs_module._cache.pop("recharge.to_address", None)

    u = _make_user(db_session)
    r = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "50", "from_address": VALID_FROM},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "RECHARGE_NOT_CONFIGURED"

    # 空字符串也算未配置
    configs_module._cache["recharge.to_address"] = ""
    r2 = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "50", "from_address": VALID_FROM},
    )
    assert r2.status_code == 400
    assert r2.json()["detail"]["error"]["code"] == "RECHARGE_NOT_CONFIGURED"


def test_create_order_uses_config_rate_and_min(client, db_session):
    """configs 设 min=10、rate=100；amount=10 → 200，rate_per_usdt=100；amount=5 → 400。"""
    configs_module._cache["recharge.min_amount_usdt"] = 10
    configs_module._cache["recharge.rate_per_usdt"] = 100

    u = _make_user(db_session)

    # 10 通过
    r_ok = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "10", "from_address": VALID_FROM},
    )
    assert r_ok.status_code == 200, r_ok.text
    assert r_ok.json()["rate_per_usdt"] == 100
    # Numeric(20,6) → 序列化为带 6 位小数的字符串
    assert Decimal(r_ok.json()["amount_usdt"]) == Decimal("10")

    # 5 拒绝
    r_no = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "5", "from_address": VALID_FROM},
    )
    assert r_no.status_code == 400
    assert r_no.json()["detail"]["error"]["code"] == "AMOUNT_TOO_SMALL"


# ---------------- GET /orders ----------------

def test_list_only_own_orders(client, db_session):
    """用户 A 看不到用户 B 的订单。"""
    a = _make_user(db_session, username="alice")
    b = _make_user(db_session, username="bob")

    client.post(
        "/api/recharge/orders",
        headers=_auth_headers(a.id),
        json={"amount_usdt": "10", "from_address": VALID_FROM},
    )
    client.post(
        "/api/recharge/orders",
        headers=_auth_headers(b.id),
        json={"amount_usdt": "20", "from_address": VALID_FROM},
    )
    client.post(
        "/api/recharge/orders",
        headers=_auth_headers(b.id),
        json={"amount_usdt": "30", "from_address": VALID_FROM},
    )

    ra = client.get("/api/recharge/orders", headers=_auth_headers(a.id))
    assert ra.status_code == 200
    body_a = ra.json()
    assert body_a["total"] == 1
    assert all(it["user_id"] == a.id for it in body_a["items"])

    rb = client.get("/api/recharge/orders", headers=_auth_headers(b.id))
    body_b = rb.json()
    assert body_b["total"] == 2
    assert all(it["user_id"] == b.id for it in body_b["items"])


def test_list_pagination(client, db_session):
    """插 5 条；page=1&size=2 / page=2&size=2 / page=3&size=2 → 各页 items 数正确，total=5。"""
    u = _make_user(db_session)
    for i in range(5):
        r = client.post(
            "/api/recharge/orders",
            headers=_auth_headers(u.id),
            json={"amount_usdt": f"{10 + i}", "from_address": VALID_FROM},
        )
        assert r.status_code == 200

    r1 = client.get(
        "/api/recharge/orders?page=1&size=2", headers=_auth_headers(u.id)
    )
    body1 = r1.json()
    assert body1["total"] == 5
    assert body1["page"] == 1
    assert body1["size"] == 2
    assert len(body1["items"]) == 2

    r2 = client.get(
        "/api/recharge/orders?page=2&size=2", headers=_auth_headers(u.id)
    )
    body2 = r2.json()
    assert body2["total"] == 5
    assert len(body2["items"]) == 2

    r3 = client.get(
        "/api/recharge/orders?page=3&size=2", headers=_auth_headers(u.id)
    )
    body3 = r3.json()
    assert body3["total"] == 5
    assert len(body3["items"]) == 1  # 5 - 2*2 = 1

    # 不重复
    ids = {item["id"] for item in body1["items"]} | \
          {item["id"] for item in body2["items"]} | \
          {item["id"] for item in body3["items"]}
    assert len(ids) == 5


# ---------------- GET /orders/{id} ----------------

def test_get_detail_ok(client, db_session):
    u = _make_user(db_session)
    r1 = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "50", "from_address": VALID_FROM},
    )
    oid = r1.json()["id"]

    r2 = client.get(f"/api/recharge/orders/{oid}", headers=_auth_headers(u.id))
    assert r2.status_code == 200
    body = r2.json()
    assert body["id"] == oid
    assert body["user_id"] == u.id
    assert body["status"] == "pending"


def test_get_detail_not_found(client, db_session):
    u = _make_user(db_session)
    r = client.get("/api/recharge/orders/99999", headers=_auth_headers(u.id))
    assert r.status_code == 404
    assert r.json()["detail"]["error"]["code"] == "ORDER_NOT_FOUND"


def test_get_detail_other_users_returns_404(client, db_session):
    """访问别人的订单也返回 404，避免泄露订单 id 是否存在。"""
    a = _make_user(db_session, username="alice")
    b = _make_user(db_session, username="bob")

    r1 = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(a.id),
        json={"amount_usdt": "50", "from_address": VALID_FROM},
    )
    oid = r1.json()["id"]

    r2 = client.get(f"/api/recharge/orders/{oid}", headers=_auth_headers(b.id))
    assert r2.status_code == 404
    assert r2.json()["detail"]["error"]["code"] == "ORDER_NOT_FOUND"


def test_create_order_snapshot_rate_immutable(client, db_session):
    """订单创建后改 configs.rate_per_usdt，订单的 rate_per_usdt 不变。"""
    configs_module._cache["recharge.rate_per_usdt"] = 60
    u = _make_user(db_session)

    r = client.post(
        "/api/recharge/orders",
        headers=_auth_headers(u.id),
        json={"amount_usdt": "50", "from_address": VALID_FROM},
    )
    assert r.status_code == 200
    oid = r.json()["id"]
    assert r.json()["rate_per_usdt"] == 60

    # 改 configs（既改 cache，也确保读路径不会再找回原值）
    configs_module._cache["recharge.rate_per_usdt"] = 999

    # 重新从 DB 读
    db_session.expire_all()
    order = db_session.get(RechargeOrder, oid)
    assert order.rate_per_usdt == 60

    # API 详情也仍是 60
    r2 = client.get(f"/api/recharge/orders/{oid}", headers=_auth_headers(u.id))
    assert r2.json()["rate_per_usdt"] == 60
