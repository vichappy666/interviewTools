"""End-to-end tests for /api/auth/* via TestClient + in-memory SQLite."""
import pytest

from app.auth.security import hash_password
from app.models.user import User


def _make_user(db, username="alice", password="secret123", phone="13800138000"):
    u = User(
        username=username,
        password_hash=hash_password(password),
        phone=phone,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------------- register ----------------

def test_register_success(client):
    r = client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "secret123", "phone": "13800138000"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"]
    assert body["user"]["username"] == "alice"
    assert body["user"]["balance_seconds"] == 0


def test_register_username_taken(client, db_session):
    _make_user(db_session, username="bobby")
    r = client.post(
        "/api/auth/register",
        json={"username": "bobby", "password": "secret123"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"]["code"] == "USERNAME_TAKEN"


def test_register_weak_password(client):
    r = client.post(
        "/api/auth/register",
        json={"username": "carol", "password": "onlyletters"},
    )
    assert r.status_code == 422
    # 422 is from pydantic validator, response shape differs; just verify it failed


def test_register_username_too_short(client):
    r = client.post(
        "/api/auth/register",
        json={"username": "ab", "password": "secret123"},
    )
    assert r.status_code == 422


# ---------------- login ----------------

def test_login_success(client, db_session):
    _make_user(db_session, username="dan", password="hunter22")
    r = client.post(
        "/api/auth/login",
        json={"username": "dan", "password": "hunter22"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["user"]["username"] == "dan"


def test_login_wrong_password(client, db_session):
    _make_user(db_session, username="eve", password="rightpw99")
    r = client.post(
        "/api/auth/login",
        json={"username": "eve", "password": "wrongpw99"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "AUTH_INVALID"


def test_login_unknown_user(client):
    r = client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "whatever1"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "AUTH_INVALID"


def test_login_throttle_after_5_failures(client, db_session):
    _make_user(db_session, username="frank", password="goodpass1")
    for _ in range(5):
        client.post(
            "/api/auth/login",
            json={"username": "frank", "password": "BAD"},
        )
    # 6th call should be throttled (regardless of correct pwd or not).
    r = client.post(
        "/api/auth/login",
        json={"username": "frank", "password": "goodpass1"},
    )
    assert r.status_code == 429
    assert r.json()["detail"]["error"]["code"] == "RATE_LIMITED"


# ---------------- reset-password ----------------

def test_reset_password_success(client, db_session):
    _make_user(db_session, username="grace", password="oldpass11", phone="13900139000")
    r = client.post(
        "/api/auth/reset-password",
        json={
            "username": "grace",
            "phone": "13900139000",
            "new_password": "newpass22",
        },
    )
    assert r.status_code == 200
    # Old password no longer works.
    r2 = client.post(
        "/api/auth/login",
        json={"username": "grace", "password": "oldpass11"},
    )
    assert r2.status_code == 401
    # New password works.
    r3 = client.post(
        "/api/auth/login",
        json={"username": "grace", "password": "newpass22"},
    )
    assert r3.status_code == 200


def test_reset_password_phone_mismatch(client, db_session):
    _make_user(db_session, username="henry", password="oldpass11", phone="13700137000")
    r = client.post(
        "/api/auth/reset-password",
        json={
            "username": "henry",
            "phone": "13800138000",  # wrong number
            "new_password": "newpass22",
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "RESET_NO_MATCH"


def test_reset_password_unknown_user(client):
    r = client.post(
        "/api/auth/reset-password",
        json={
            "username": "nobody",
            "phone": "13800138000",
            "new_password": "whatever11",
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "RESET_NO_MATCH"
