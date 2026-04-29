"""Tests for recharge_orders ORM model (M3 T1)."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.security import hash_password
from app.models.recharge_order import RechargeOrder
from app.models.user import User


def _make_user(db, username="alice", password="secret123"):
    u = User(username=username, password_hash=hash_password(password))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_order(
    user_id,
    amount="50.000000",
    from_address="TFromAddrXXXXXXXXXXXXXXXXXXXXXXXXX",
    to_address="TToAddrYYYYYYYYYYYYYYYYYYYYYYYYYY",
    tx_hash=None,
    expires_in_hours=24,
):
    return RechargeOrder(
        user_id=user_id,
        amount_usdt=Decimal(amount),
        from_address=from_address,
        to_address=to_address,
        tx_hash=tx_hash,
        expires_at=datetime.utcnow() + timedelta(hours=expires_in_hours),
    )


def test_create_pending_order(db_session):
    """插入一条最小字段订单 → query 成功，status='pending'。"""
    u = _make_user(db_session)
    order = _make_order(u.id)
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)

    fetched = db_session.query(RechargeOrder).filter_by(id=order.id).one()
    assert fetched.user_id == u.id
    assert fetched.status == "pending"
    assert fetched.amount_usdt == Decimal("50.000000")
    assert fetched.from_address == "TFromAddrXXXXXXXXXXXXXXXXXXXXXXXXX"
    assert fetched.to_address == "TToAddrYYYYYYYYYYYYYYYYYYYYYYYYYY"
    assert fetched.tx_hash is None
    assert fetched.tx_amount_usdt is None
    assert fetched.granted_seconds is None
    assert fetched.rate_per_usdt is None
    assert fetched.fail_reason is None
    assert fetched.succeeded_at is None


def test_default_values(db_session):
    """默认 status='pending'，created_at/updated_at 自动填。"""
    u = _make_user(db_session)
    order = _make_order(u.id)
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)

    assert order.status == "pending"
    assert order.created_at is not None
    assert order.updated_at is not None
    assert order.succeeded_at is None


def test_distinct_tx_hash_ok(db_session):
    """两条订单不同 tx_hash 都能插入。"""
    u = _make_user(db_session)
    o1 = _make_order(u.id, tx_hash="0xhash_aaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    o2 = _make_order(u.id, tx_hash="0xhash_bbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    db_session.add_all([o1, o2])
    db_session.commit()

    rows = db_session.query(RechargeOrder).order_by(RechargeOrder.id).all()
    assert len(rows) == 2
    assert rows[0].tx_hash == "0xhash_aaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert rows[1].tx_hash == "0xhash_bbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_duplicate_tx_hash_raises(db_session):
    """同一 tx_hash 第二次插入抛 IntegrityError。"""
    u = _make_user(db_session)
    same_hash = "0xhash_dup_dup_dup_dup_dup_dup_dup_dup"
    o1 = _make_order(u.id, tx_hash=same_hash)
    db_session.add(o1)
    db_session.commit()

    o2 = _make_order(u.id, tx_hash=same_hash)
    db_session.add(o2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_expires_at_storage(db_session):
    """能存 24h 后的 datetime。"""
    u = _make_user(db_session)
    expected_expires = datetime.utcnow() + timedelta(hours=24)
    order = RechargeOrder(
        user_id=u.id,
        amount_usdt=Decimal("10.000000"),
        from_address="TFrom",
        to_address="TTo",
        expires_at=expected_expires,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)

    # SQLite 存为 datetime；允许微秒级误差
    delta = abs((order.expires_at - expected_expires).total_seconds())
    assert delta < 1.0
    # 至少是未来时间
    assert order.expires_at > datetime.utcnow()


def test_decimal_precision(db_session):
    """amount_usdt=Decimal('50.123456') 写入读出无精度丢失。"""
    u = _make_user(db_session)
    order = RechargeOrder(
        user_id=u.id,
        amount_usdt=Decimal("50.123456"),
        from_address="TFrom",
        to_address="TTo",
        tx_amount_usdt=Decimal("49.999999"),
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)

    fetched = db_session.query(RechargeOrder).filter_by(id=order.id).one()
    assert fetched.amount_usdt == Decimal("50.123456")
    assert fetched.tx_amount_usdt == Decimal("49.999999")


def test_status_enum_definition(db_session):
    """recharge_orders.status ENUM 定义为 6 值。"""
    from sqlalchemy import Enum as SAEnum

    col = RechargeOrder.__table__.c.status
    assert col.nullable is False
    assert isinstance(col.type, SAEnum)
    assert set(col.type.enums) == {
        "pending",
        "submitted",
        "verifying",
        "succeeded",
        "failed",
        "expired",
    }
    assert col.type.name == "recharge_status"
