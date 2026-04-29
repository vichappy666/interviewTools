"""End-to-end tests for /api/users/me*."""
from app.auth.security import hash_password, make_user_token
from app.models.user import User


def _make_user(db, username="alice", password="secret123", phone=None, balance=0):
    u = User(
        username=username,
        password_hash=hash_password(password),
        phone=phone,
        balance_seconds=balance,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth_headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {make_user_token(user_id)}"}


# ---------------- GET /me ----------------

def test_get_me_requires_token(client):
    r = client.get("/api/users/me")
    assert r.status_code == 401


def test_get_me_with_invalid_token(client):
    r = client.get("/api/users/me", headers={"Authorization": "Bearer not.a.token"})
    assert r.status_code == 401


def test_get_me_with_valid_token(client, db_session):
    u = _make_user(db_session, username="alice", balance=3600)
    r = client.get("/api/users/me", headers=_auth_headers(u.id))
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "alice"
    assert body["balance_seconds"] == 3600


def test_get_me_admin_token_rejected(client, db_session):
    """A token with type=admin should not work on /api/users/me."""
    from app.auth.security import make_admin_token
    u = _make_user(db_session, username="alice")
    # Create admin token but with id=u.id (irrelevant — we test type mismatch).
    headers = {"Authorization": f"Bearer {make_admin_token(u.id)}"}
    r = client.get("/api/users/me", headers=headers)
    assert r.status_code == 401


# ---------------- PATCH /me ----------------

def test_patch_me_set_phone(client, db_session):
    u = _make_user(db_session, username="bobby")
    r = client.patch(
        "/api/users/me",
        json={"phone": "13800138000"},
        headers=_auth_headers(u.id),
    )
    assert r.status_code == 200
    assert r.json()["phone"] == "13800138000"


def test_patch_me_clear_phone(client, db_session):
    u = _make_user(db_session, username="carol", phone="13800138000")
    r = client.patch(
        "/api/users/me",
        json={"phone": None},
        headers=_auth_headers(u.id),
    )
    assert r.status_code == 200
    assert r.json()["phone"] is None


def test_patch_me_invalid_phone(client, db_session):
    u = _make_user(db_session, username="dan")
    r = client.patch(
        "/api/users/me",
        json={"phone": "not-a-number"},
        headers=_auth_headers(u.id),
    )
    assert r.status_code == 422


# ---------------- change-password ----------------

def test_change_password_success(client, db_session):
    u = _make_user(db_session, username="eve", password="oldpass11")
    r = client.post(
        "/api/users/me/change-password",
        json={"old_password": "oldpass11", "new_password": "newpass22"},
        headers=_auth_headers(u.id),
    )
    assert r.status_code == 200
    # Old password no longer logs in
    r2 = client.post("/api/auth/login", json={"username": "eve", "password": "oldpass11"})
    assert r2.status_code == 401
    # New password logs in
    r3 = client.post("/api/auth/login", json={"username": "eve", "password": "newpass22"})
    assert r3.status_code == 200


def test_change_password_old_wrong(client, db_session):
    u = _make_user(db_session, username="frank", password="oldpass11")
    r = client.post(
        "/api/users/me/change-password",
        json={"old_password": "WRONG", "new_password": "newpass22"},
        headers=_auth_headers(u.id),
    )
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "AUTH_INVALID"


def test_change_password_weak_new(client, db_session):
    u = _make_user(db_session, username="grace", password="oldpass11")
    r = client.post(
        "/api/users/me/change-password",
        json={"old_password": "oldpass11", "new_password": "onlyletters"},
        headers=_auth_headers(u.id),
    )
    assert r.status_code == 422
