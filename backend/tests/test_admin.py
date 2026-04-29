"""End-to-end tests for /api/admin/*."""
from app.auth.security import hash_password, make_admin_token, make_user_token
from app.models.admin import Admin
from app.models.admin_audit_log import AdminAuditLog
from app.models.balance_ledger import BalanceLedger
from app.models.user import User


def _make_admin(db, username="admin", password="admin"):
    a = Admin(username=username, password_hash=hash_password(password))
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_user(db, username="alice", balance=0, phone=None):
    u = User(
        username=username,
        password_hash=hash_password("secret123"),
        phone=phone,
        balance_seconds=balance,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _admin_headers(admin_id: int) -> dict:
    return {"Authorization": f"Bearer {make_admin_token(admin_id)}"}


# ---------------- admin login ----------------

def test_admin_login_success(client, db_session):
    _make_admin(db_session)
    r = client.post(
        "/api/admin/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["admin"]["username"] == "admin"


def test_admin_login_wrong_password(client, db_session):
    _make_admin(db_session)
    r = client.post(
        "/api/admin/auth/login", json={"username": "admin", "password": "WRONG"}
    )
    assert r.status_code == 401


# ---------------- type isolation ----------------

def test_admin_endpoint_rejects_user_token(client, db_session):
    u = _make_user(db_session)
    headers = {"Authorization": f"Bearer {make_user_token(u.id)}"}
    r = client.get("/api/admin/users", headers=headers)
    assert r.status_code == 401


def test_admin_endpoint_requires_token(client):
    r = client.get("/api/admin/users")
    assert r.status_code == 401


# ---------------- list users ----------------

def test_list_users_basic(client, db_session):
    a = _make_admin(db_session)
    _make_user(db_session, username="alice")
    _make_user(db_session, username="bobby")
    r = client.get("/api/admin/users", headers=_admin_headers(a.id))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    names = {item["username"] for item in body["items"]}
    assert names == {"alice", "bobby"}


def test_list_users_search_q(client, db_session):
    a = _make_admin(db_session)
    _make_user(db_session, username="alice")
    _make_user(db_session, username="albert")
    _make_user(db_session, username="bobby")
    r = client.get("/api/admin/users?q=al", headers=_admin_headers(a.id))
    body = r.json()
    assert body["total"] == 2
    names = {item["username"] for item in body["items"]}
    assert names == {"alice", "albert"}


# ---------------- user detail ----------------

def test_user_detail(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session, username="carol", balance=500)
    r = client.get(f"/api/admin/users/{u.id}", headers=_admin_headers(a.id))
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["username"] == "carol"
    assert body["recent_ledger"] == []
    assert body["recent_sessions"] == []


def test_user_detail_not_found(client, db_session):
    a = _make_admin(db_session)
    r = client.get("/api/admin/users/99999", headers=_admin_headers(a.id))
    assert r.status_code == 404


# ---------------- patch user (status) ----------------

def test_patch_user_ban(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session, username="dan")
    r = client.patch(
        f"/api/admin/users/{u.id}", json={"status": 0}, headers=_admin_headers(a.id)
    )
    assert r.status_code == 200
    assert r.json()["status"] == 0
    # Verify audit log written
    audit = db_session.query(AdminAuditLog).all()
    assert len(audit) == 1
    assert audit[0].action == "patch_user"
    assert audit[0].target_id == str(u.id)


# ---------------- grant balance ----------------

def test_grant_balance_positive(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session, username="eve", balance=0)
    r = client.post(
        f"/api/admin/users/{u.id}/grant",
        json={"delta_seconds": 3600, "note": "M1 验收"},
        headers=_admin_headers(a.id),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["balance_seconds"] == 3600

    # Ledger row written
    ledger = db_session.query(BalanceLedger).filter_by(user_id=u.id).all()
    assert len(ledger) == 1
    assert ledger[0].delta_seconds == 3600
    assert ledger[0].reason == "admin_grant"
    assert ledger[0].note == "M1 验收"

    # Audit row written
    audit = db_session.query(AdminAuditLog).all()
    assert len(audit) == 1
    assert audit[0].action == "grant_balance"
    assert audit[0].note == "M1 验收"


def test_grant_balance_negative_then_overdraw(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session, balance=100)
    # Negative within balance OK
    r1 = client.post(
        f"/api/admin/users/{u.id}/grant",
        json={"delta_seconds": -50, "note": "扣点"},
        headers=_admin_headers(a.id),
    )
    assert r1.status_code == 200
    assert r1.json()["balance_seconds"] == 50
    # Overdraw fails
    r2 = client.post(
        f"/api/admin/users/{u.id}/grant",
        json={"delta_seconds": -200, "note": "再扣"},
        headers=_admin_headers(a.id),
    )
    assert r2.status_code == 400
    assert r2.json()["detail"]["error"]["code"] == "INSUFFICIENT_BALANCE"


def test_grant_balance_requires_note(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session)
    r = client.post(
        f"/api/admin/users/{u.id}/grant",
        json={"delta_seconds": 100},  # no note
        headers=_admin_headers(a.id),
    )
    assert r.status_code == 422


def test_grant_balance_zero_rejected(client, db_session):
    a = _make_admin(db_session)
    u = _make_user(db_session)
    r = client.post(
        f"/api/admin/users/{u.id}/grant",
        json={"delta_seconds": 0, "note": "zero"},
        headers=_admin_headers(a.id),
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "INVALID_DELTA"
