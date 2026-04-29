"""Tests for configs cache + admin /api/admin/configs."""
import asyncio

import pytest

from app import configs
from app import configs as configs_module
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


# ---------------- watcher (_refresh_loop / start_watcher / stop_watcher) ----------------


@pytest.fixture(autouse=True)
def _reset_watcher():
    """每个测试前后把 module 级 _watcher_task 重置 / cancel 清理。"""
    configs_module._watcher_task = None
    yield
    task = configs_module._watcher_task
    if task is not None:
        task.cancel()
        configs_module._watcher_task = None


@pytest.mark.asyncio
async def test_watcher_picks_up_external_change(db_session, monkeypatch):
    """Watcher 应该重新读 DB，包括别处直接 INSERT/UPDATE 的 row。"""
    # seed 一个 key
    db_session.add(ConfigKV(key="watcher.key", value="v1"))
    db_session.commit()
    configs_module.init_cache(db_session)
    assert configs_module.get("watcher.key") == "v1"

    # 模拟 DBA 直接改 DB（绕过 save，所以 _cache 没更新）
    row = db_session.query(ConfigKV).filter_by(key="watcher.key").one()
    row.value = "v2"
    db_session.commit()
    assert configs_module.get("watcher.key") == "v1"  # 缓存还是旧的

    # 让 _refresh_loop 用 db_session 的同一个 engine
    bind = db_session.get_bind()
    from sqlalchemy.orm import sessionmaker
    TestSession = sessionmaker(bind=bind, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.configs.SessionLocal", TestSession)

    # 让 sleep：第一次直接返回（让 loop 跑一圈 refresh body），第二次 raise CancelledError
    sleep_count = {"n": 0}

    async def fast_sleep(seconds):
        sleep_count["n"] += 1
        if sleep_count["n"] > 1:
            raise asyncio.CancelledError()
        # 第一次直接返回，让循环执行 refresh body

    monkeypatch.setattr("app.configs.asyncio.sleep", fast_sleep)

    try:
        await configs_module._refresh_loop(interval_seconds=1)
    except asyncio.CancelledError:
        pass

    # 现在缓存应当是 v2
    assert configs_module.get("watcher.key") == "v2"


@pytest.mark.asyncio
async def test_watcher_recovers_from_db_error(monkeypatch):
    """DB 一次失败不应停止 loop，下次还要重试。"""
    call_count = {"n": 0}

    class FakeSession:
        def query(self, *a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated DB hiccup")

            class FakeQuery:
                def all(self_inner):
                    return []

            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr("app.configs.SessionLocal", FakeSession)

    sleep_count = {"n": 0}

    async def fast_sleep(s):
        sleep_count["n"] += 1
        if sleep_count["n"] > 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr("app.configs.asyncio.sleep", fast_sleep)

    try:
        await configs_module._refresh_loop(interval_seconds=1)
    except asyncio.CancelledError:
        pass

    # 第二次 query 成功了，没抛上层 → loop 没死
    assert call_count["n"] >= 2


@pytest.mark.asyncio
async def test_start_watcher_returns_running_task(monkeypatch):
    """start_watcher 应该返回 alive 的 task；stop_watcher 后退出。"""
    real_sleep = asyncio.sleep

    async def slow_sleep(s):
        await real_sleep(0.05)

    monkeypatch.setattr("app.configs.asyncio.sleep", slow_sleep)

    # 让 SessionLocal 返回 empty 结果（不写 DB）
    class FakeSession:
        def query(self, *a, **kw):
            class FakeQuery:
                def all(self_inner):
                    return []

            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr("app.configs.SessionLocal", FakeSession)

    loop = asyncio.get_running_loop()
    task = configs_module.start_watcher(loop, interval_seconds=1)
    assert not task.done()

    await asyncio.sleep(0.1)
    assert not task.done()  # 还在跑

    await configs_module.stop_watcher()
    assert task.done()


@pytest.mark.asyncio
async def test_stop_watcher_idempotent():
    """stop_watcher 没有 task 时不抛。"""
    configs_module._watcher_task = None
    await configs_module.stop_watcher()  # 不抛即通过
