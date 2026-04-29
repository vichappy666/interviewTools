"""Tests for configs cache + admin /api/admin/configs."""
from app import configs
from app.auth.security import hash_password, make_admin_token, make_user_token
from app.models.admin import Admin
from app.models.config_kv import ConfigKV
from app.models.user import User


def _make_admin(db, username="admin", password="admin"):
    a = Admin(username=username, password_hash=hash_password(password))
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _admin_headers(admin_id: int) -> dict:
    return {"Authorization": f"Bearer {make_admin_token(admin_id)}"}


# ---------------- configs module ----------------

def test_init_cache_loads_db_rows(db_session):
    db_session.add(ConfigKV(key="foo.bar", value={"hello": "world"}))
    db_session.add(ConfigKV(key="num.one", value=42))
    db_session.commit()
    configs.init_cache(db_session)
    assert configs.get("foo.bar") == {"hello": "world"}
    assert configs.get("num.one") == 42
    assert configs.get("missing", "default") == "default"


def test_save_updates_cache_immediately(db_session):
    configs.init_cache(db_session)
    configs.save(db_session, "session.max_concurrent", 10)
    assert configs.get("session.max_concurrent") == 10
    # And persisted
    row = db_session.query(ConfigKV).filter_by(key="session.max_concurrent").one()
    assert row.value == 10


def test_save_overwrite(db_session):
    configs.save(db_session, "k", "v1")
    configs.save(db_session, "k", "v2")
    assert configs.get("k") == "v2"


def test_all_keys_snapshot(db_session):
    configs.save(db_session, "a", 1)
    configs.save(db_session, "b", "x")
    snap = configs.all_keys()
    assert snap.get("a") == 1
    assert snap.get("b") == "x"


# ---------------- /api/admin/configs ----------------

def test_list_configs_requires_admin(client):
    r = client.get("/api/admin/configs")
    assert r.status_code == 401


def test_list_configs_user_token_rejected(client, db_session):
    u = User(username="alice", password_hash=hash_password("secret123"))
    db_session.add(u)
    db_session.commit()
    headers = {"Authorization": f"Bearer {make_user_token(u.id)}"}
    r = client.get("/api/admin/configs", headers=headers)
    assert r.status_code == 401


def test_list_configs_returns_rows(client, db_session):
    a = _make_admin(db_session)
    db_session.add(ConfigKV(key="aa", value={"x": 1}))
    db_session.add(ConfigKV(key="bb", value=2))
    db_session.commit()
    r = client.get("/api/admin/configs", headers=_admin_headers(a.id))
    assert r.status_code == 200
    items = {item["key"]: item["value"] for item in r.json()}
    assert items["aa"] == {"x": 1}
    assert items["bb"] == 2


def test_put_config_creates_new(client, db_session):
    a = _make_admin(db_session)
    r = client.put(
        "/api/admin/configs/feature.flag",
        json={"value": True},
        headers=_admin_headers(a.id),
    )
    assert r.status_code == 200
    assert r.json() == {"key": "feature.flag", "value": True}
    assert configs.get("feature.flag") is True


def test_put_config_updates_existing_and_writes_audit(client, db_session):
    a = _make_admin(db_session)
    db_session.add(ConfigKV(key="x", value=1))
    db_session.commit()
    configs.init_cache(db_session)

    r = client.put("/api/admin/configs/x", json={"value": 999}, headers=_admin_headers(a.id))
    assert r.status_code == 200
    assert r.json()["value"] == 999

    from app.models.admin_audit_log import AdminAuditLog
    audits = db_session.query(AdminAuditLog).filter_by(action="update_config").all()
    assert len(audits) == 1
    assert audits[0].target_id == "x"


def test_put_config_supports_complex_json(client, db_session):
    a = _make_admin(db_session)
    payload = {"providers": [{"name": "deepseek", "api_key": "sk-xxx"}]}
    r = client.put(
        "/api/admin/configs/llm.providers",
        json={"value": payload},
        headers=_admin_headers(a.id),
    )
    assert r.status_code == 200
    assert r.json()["value"] == payload
    assert configs.get("llm.providers") == payload
