"""End-to-end tests for /api/sessions/* (M2 T3)."""
import pytest

from app import configs as configs_module
from app.auth.security import hash_password, make_user_token
from app.models.session import Session as SessionModel
from app.models.user import User


def _make_user(db, username="alice", password="secret123", balance=3600):
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
    """每个测试运行前后清空 configs 缓存，避免 max_concurrent 串扰。"""
    configs_module._cache.clear()
    yield
    configs_module._cache.clear()


# ---------------- POST /start ----------------

def test_start_requires_auth(client):
    r = client.post("/api/sessions/start")
    assert r.status_code == 401


def test_start_success(client, db_session):
    u = _make_user(db_session, balance=3600)
    r = client.post("/api/sessions/start", headers=_auth_headers(u.id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["session_id"], int)
    assert body["ws_url"] == f"/ws/session/{body['session_id']}"

    # DB 中应该有 1 个 active session
    rows = (
        db_session.query(SessionModel)
        .filter(SessionModel.user_id == u.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "active"
    assert rows[0].total_seconds == 0
    assert rows[0].ended_at is None


def test_start_insufficient_balance(client, db_session):
    u = _make_user(db_session, balance=0)
    r = client.post("/api/sessions/start", headers=_auth_headers(u.id))
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "INSUFFICIENT_BALANCE"

    # 不应该插入 session
    assert db_session.query(SessionModel).filter_by(user_id=u.id).count() == 0


def test_start_session_limit(client, db_session):
    """max_concurrent=2 + 已有 2 个 active → 400 SESSION_LIMIT。"""
    configs_module._cache["session.max_concurrent"] = 2

    u = _make_user(db_session, balance=3600)
    # 直接造 2 个 active session
    for _ in range(2):
        s = SessionModel(user_id=u.id, status="active", total_seconds=0)
        db_session.add(s)
    db_session.commit()

    r = client.post("/api/sessions/start", headers=_auth_headers(u.id))
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "SESSION_LIMIT"


def test_start_below_session_limit(client, db_session):
    """max_concurrent=3 + 已有 2 个 active → 允许 start。"""
    configs_module._cache["session.max_concurrent"] = 3

    u = _make_user(db_session, balance=3600)
    for _ in range(2):
        s = SessionModel(user_id=u.id, status="active", total_seconds=0)
        db_session.add(s)
    db_session.commit()

    r = client.post("/api/sessions/start", headers=_auth_headers(u.id))
    assert r.status_code == 200


# ---------------- POST /{id}/stop ----------------

def test_stop_success(client, db_session):
    u = _make_user(db_session, balance=3600)
    r1 = client.post("/api/sessions/start", headers=_auth_headers(u.id))
    sid = r1.json()["session_id"]

    r2 = client.post(f"/api/sessions/{sid}/stop", headers=_auth_headers(u.id))
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "ended"
    assert body["end_reason"] == "user_stop"
    assert body["ended_at"] is not None


def test_stop_idempotent(client, db_session):
    """stop 两次都返回 200，第二次仍是 ended。"""
    u = _make_user(db_session, balance=3600)
    r1 = client.post("/api/sessions/start", headers=_auth_headers(u.id))
    sid = r1.json()["session_id"]

    r2 = client.post(f"/api/sessions/{sid}/stop", headers=_auth_headers(u.id))
    assert r2.status_code == 200
    first_ended_at = r2.json()["ended_at"]

    r3 = client.post(f"/api/sessions/{sid}/stop", headers=_auth_headers(u.id))
    assert r3.status_code == 200
    body = r3.json()
    assert body["status"] == "ended"
    assert body["end_reason"] == "user_stop"
    # 幂等：第二次不应该更新 ended_at
    assert body["ended_at"] == first_ended_at


def test_stop_not_found(client, db_session):
    u = _make_user(db_session, balance=3600)
    r = client.post("/api/sessions/99999/stop", headers=_auth_headers(u.id))
    assert r.status_code == 404
    assert r.json()["detail"]["error"]["code"] == "SESSION_NOT_FOUND"


def test_stop_forbidden(client, db_session):
    """用户 A 的 session 被用户 B stop → 403。"""
    a = _make_user(db_session, username="alice", balance=3600)
    b = _make_user(db_session, username="bob", balance=3600)

    r1 = client.post("/api/sessions/start", headers=_auth_headers(a.id))
    sid = r1.json()["session_id"]

    r2 = client.post(f"/api/sessions/{sid}/stop", headers=_auth_headers(b.id))
    assert r2.status_code == 403
    assert r2.json()["detail"]["error"]["code"] == "FORBIDDEN"


# ---------------- GET /active ----------------

def test_active_list(client, db_session):
    """start 2 个，再 stop 1 个 → /active 只返 1 个。"""
    u = _make_user(db_session, balance=3600)
    r1 = client.post("/api/sessions/start", headers=_auth_headers(u.id))
    r2 = client.post("/api/sessions/start", headers=_auth_headers(u.id))
    sid1 = r1.json()["session_id"]
    sid2 = r2.json()["session_id"]

    # stop sid1
    client.post(f"/api/sessions/{sid1}/stop", headers=_auth_headers(u.id))

    r = client.get("/api/sessions/active", headers=_auth_headers(u.id))
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == sid2
    assert items[0]["status"] == "active"


def test_active_list_isolated_per_user(client, db_session):
    a = _make_user(db_session, username="alice", balance=3600)
    b = _make_user(db_session, username="bob", balance=3600)
    client.post("/api/sessions/start", headers=_auth_headers(a.id))
    client.post("/api/sessions/start", headers=_auth_headers(b.id))

    ra = client.get("/api/sessions/active", headers=_auth_headers(a.id))
    items_a = ra.json()
    assert len(items_a) == 1
    assert items_a[0]["user_id"] == a.id


# ---------------- GET / (history paginate) ----------------

def test_history_paginate(client, db_session):
    """插 5 个 session（混 active/ended），分页 size=2 page=2 → 拿到正确切片 + total=5。"""
    u = _make_user(db_session, balance=3600)
    sids = []
    for _ in range(5):
        r = client.post("/api/sessions/start", headers=_auth_headers(u.id))
        sids.append(r.json()["session_id"])
    # stop 2 个，剩 3 个 active
    client.post(f"/api/sessions/{sids[0]}/stop", headers=_auth_headers(u.id))
    client.post(f"/api/sessions/{sids[2]}/stop", headers=_auth_headers(u.id))

    r = client.get("/api/sessions/?page=2&size=2", headers=_auth_headers(u.id))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["page"] == 2
    assert body["size"] == 2
    assert len(body["items"]) == 2


def test_history_isolated_per_user(client, db_session):
    a = _make_user(db_session, username="alice", balance=3600)
    b = _make_user(db_session, username="bob", balance=3600)
    client.post("/api/sessions/start", headers=_auth_headers(a.id))
    client.post("/api/sessions/start", headers=_auth_headers(a.id))
    client.post("/api/sessions/start", headers=_auth_headers(b.id))

    ra = client.get("/api/sessions/", headers=_auth_headers(a.id))
    body = ra.json()
    assert body["total"] == 2
    for item in body["items"]:
        assert item["user_id"] == a.id


# ---------------- GET /{id}/qa ----------------

def test_qa_empty(client, db_session):
    """stop 后 GET /{id}/qa → 200 + []。"""
    u = _make_user(db_session, balance=3600)
    r1 = client.post("/api/sessions/start", headers=_auth_headers(u.id))
    sid = r1.json()["session_id"]
    client.post(f"/api/sessions/{sid}/stop", headers=_auth_headers(u.id))

    r = client.get(f"/api/sessions/{sid}/qa", headers=_auth_headers(u.id))
    assert r.status_code == 200
    assert r.json() == []


def test_qa_not_found(client, db_session):
    u = _make_user(db_session, balance=3600)
    r = client.get("/api/sessions/99999/qa", headers=_auth_headers(u.id))
    assert r.status_code == 404
    assert r.json()["detail"]["error"]["code"] == "SESSION_NOT_FOUND"


def test_qa_forbidden(client, db_session):
    a = _make_user(db_session, username="alice", balance=3600)
    b = _make_user(db_session, username="bob", balance=3600)
    r1 = client.post("/api/sessions/start", headers=_auth_headers(a.id))
    sid = r1.json()["session_id"]

    r = client.get(f"/api/sessions/{sid}/qa", headers=_auth_headers(b.id))
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "FORBIDDEN"


def test_list_qa_returns_rows_in_order(client, db_session):
    """已结束的 session，2 条 QA，按 asked_at ASC 返回。"""
    from datetime import datetime, timedelta
    from app.models.session_qa import SessionQA
    from app.models.session import Session as SessionModel
    from app.models.user import User
    from app.auth.security import hash_password, make_user_token

    u = User(username="qa_alice", password_hash=hash_password("secret123"), balance_seconds=100)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)

    s = SessionModel(user_id=u.id, status="ended", total_seconds=60)
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)

    base = datetime.utcnow()
    qa1 = SessionQA(
        session_id=s.id, question="Q1",
        answer_key_points="K1", answer_script="S1", answer_full="F1",
        asked_at=base, finished_at=base + timedelta(seconds=2),
        source="detected",
    )
    qa2 = SessionQA(
        session_id=s.id, question="Q2",
        answer_key_points="K2", answer_script="S2", answer_full="F2",
        asked_at=base + timedelta(seconds=10), finished_at=base + timedelta(seconds=12),
        source="manual",
    )
    db_session.add_all([qa1, qa2])
    db_session.commit()

    r = client.get(
        f"/api/sessions/{s.id}/qa",
        headers={"Authorization": f"Bearer {make_user_token(u.id)}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert body[0]["question"] == "Q1"
    assert body[0]["answer_key_points"] == "K1"
    assert body[1]["question"] == "Q2"
    assert body[1]["source"] == "manual"


def test_list_qa_returns_unfinished_qa(client, db_session):
    """answer_* 全是 None 的未完成 QA 也要返回。"""
    from app.models.session_qa import SessionQA
    from app.models.session import Session as SessionModel
    from app.models.user import User
    from app.auth.security import hash_password, make_user_token

    u = User(username="qa_bob", password_hash=hash_password("secret123"), balance_seconds=100)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)

    s = SessionModel(user_id=u.id, status="active", total_seconds=0)
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)

    qa = SessionQA(
        session_id=s.id, question="Q-pending",
        answer_key_points=None, answer_script=None, answer_full=None,
        finished_at=None, source="detected",
    )
    db_session.add(qa)
    db_session.commit()

    r = client.get(
        f"/api/sessions/{s.id}/qa",
        headers={"Authorization": f"Bearer {make_user_token(u.id)}"},
    )
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["answer_key_points"] is None
    assert r.json()[0]["finished_at"] is None
