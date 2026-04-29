"""Tests for billing.ledger.grant and /api/balance/ledger."""
import pytest

from app.auth.security import hash_password, make_user_token
from app.billing.ledger import grant
from app.models.balance_ledger import BalanceLedger
from app.models.user import User


def _make_user(db, username="alice", balance=0):
    u = User(username=username, password_hash=hash_password("secret123"), balance_seconds=balance)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------------- grant() unit tests ----------------

def test_grant_positive_adds_balance(db_session):
    u = _make_user(db_session, balance=0)
    new_balance = grant(db_session, u.id, 3600, reason="admin_grant", note="test")
    assert new_balance == 3600

    db_session.refresh(u)
    assert u.balance_seconds == 3600

    rows = db_session.query(BalanceLedger).filter(BalanceLedger.user_id == u.id).all()
    assert len(rows) == 1
    assert rows[0].delta_seconds == 3600
    assert rows[0].balance_after == 3600
    assert rows[0].reason == "admin_grant"


def test_grant_negative_within_balance(db_session):
    u = _make_user(db_session, balance=1000)
    new_balance = grant(db_session, u.id, -300, reason="session", ref_type="session", ref_id=42)
    assert new_balance == 700

    db_session.refresh(u)
    assert u.balance_seconds == 700


def test_grant_negative_overdraw_raises(db_session):
    from fastapi import HTTPException

    u = _make_user(db_session, balance=100)
    with pytest.raises(HTTPException) as exc:
        grant(db_session, u.id, -200, reason="session")
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "INSUFFICIENT_BALANCE"

    # Balance unchanged
    db_session.refresh(u)
    assert u.balance_seconds == 100
    # No ledger row created
    assert db_session.query(BalanceLedger).count() == 0


def test_grant_unknown_user_raises(db_session):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        grant(db_session, 99999, 100, reason="admin_grant")
    assert exc.value.status_code == 404


def test_grant_invalid_reason_raises(db_session):
    u = _make_user(db_session)
    with pytest.raises(ValueError):
        grant(db_session, u.id, 100, reason="invalid_reason_xxx")


def test_grant_multiple_writes_balance_after_correct(db_session):
    u = _make_user(db_session, balance=0)
    grant(db_session, u.id, 1000, reason="recharge")
    grant(db_session, u.id, 2000, reason="recharge")
    grant(db_session, u.id, -500, reason="session")

    rows = (
        db_session.query(BalanceLedger)
        .filter(BalanceLedger.user_id == u.id)
        .order_by(BalanceLedger.id.asc())
        .all()
    )
    assert [r.delta_seconds for r in rows] == [1000, 2000, -500]
    assert [r.balance_after for r in rows] == [1000, 3000, 2500]

    db_session.refresh(u)
    assert u.balance_seconds == 2500


# ---------------- /api/balance/ledger ----------------

def test_ledger_endpoint_requires_auth(client):
    r = client.get("/api/balance/ledger")
    assert r.status_code == 401


def test_ledger_empty(client, db_session):
    u = _make_user(db_session)
    headers = {"Authorization": f"Bearer {make_user_token(u.id)}"}
    r = client.get("/api/balance/ledger", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_ledger_lists_in_descending_time(client, db_session):
    u = _make_user(db_session)
    grant(db_session, u.id, 1000, reason="recharge")
    grant(db_session, u.id, 2000, reason="recharge")
    grant(db_session, u.id, -500, reason="session")

    headers = {"Authorization": f"Bearer {make_user_token(u.id)}"}
    r = client.get("/api/balance/ledger", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    # Most recent first
    deltas = [item["delta_seconds"] for item in body["items"]]
    assert deltas == [-500, 2000, 1000]


def test_ledger_pagination(client, db_session):
    u = _make_user(db_session)
    for i in range(25):
        grant(db_session, u.id, 100, reason="recharge", note=f"#{i}")

    headers = {"Authorization": f"Bearer {make_user_token(u.id)}"}
    r1 = client.get("/api/balance/ledger?page=1&size=10", headers=headers)
    r2 = client.get("/api/balance/ledger?page=3&size=10", headers=headers)

    assert r1.json()["total"] == 25
    assert len(r1.json()["items"]) == 10
    assert len(r2.json()["items"]) == 5  # page 3 has only 5


def test_ledger_isolated_per_user(client, db_session):
    u1 = _make_user(db_session, username="alice")
    u2 = _make_user(db_session, username="bob")
    grant(db_session, u1.id, 100, reason="recharge")
    grant(db_session, u1.id, 200, reason="recharge")
    grant(db_session, u2.id, 50, reason="recharge")

    h1 = {"Authorization": f"Bearer {make_user_token(u1.id)}"}
    r = client.get("/api/balance/ledger", headers=h1)
    body = r.json()
    assert body["total"] == 2
    deltas = [item["delta_seconds"] for item in body["items"]]
    assert sorted(deltas) == [100, 200]
