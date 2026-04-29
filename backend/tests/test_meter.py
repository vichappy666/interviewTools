"""扣费心跳 meter 测试（重构后：会话结束时一次性写 ledger）。

设计变更：
- 每秒不再写 balance_ledger（不再调 grant），只在内存 _session_elapsed 累加
- 余额检查 = user.balance_seconds - sum(elapsed) ≤ 0 → stop_all_for_user
- session 结束时调 flush_session_charge() 一次性写 ledger 行
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.sessions import meter as meter_mod
from app.sessions.meter import (
    _reset_for_tests,
    ensure_running,
    flush_session_charge,
    get_session_elapsed,
    stop_for_user,
)


# ============== fixtures ==============


@pytest.fixture(autouse=True)
def _reset_state():
    _reset_for_tests()
    yield
    _reset_for_tests()


class FakeSessionRow:
    def __init__(self, sid: int, user_id: int, status: str = "active") -> None:
        self.id = sid
        self.user_id = user_id
        self.status = status


class FakeUser:
    def __init__(self, uid: int, balance: int) -> None:
        self.id = uid
        self.balance_seconds = balance


class FakeQuery:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._items)

    def one_or_none(self):
        return self._items[0] if self._items else None

    def one(self):
        return self._items[0]


class FakeDB:
    def __init__(
        self, sessions: list[FakeSessionRow], user: FakeUser | None
    ) -> None:
        self.sessions = sessions
        self.user = user
        self._closed = False

    def query(self, model):
        from app.models.session import Session as SessionModel
        from app.models.user import User

        if model is SessionModel:
            return FakeQuery(list(self.sessions))
        if model is User:
            return FakeQuery([self.user] if self.user else [])
        return FakeQuery([])

    def close(self):
        self._closed = True


@pytest.fixture
def patched_session_local(monkeypatch):
    state: dict[str, Any] = {"sessions": [], "user": None, "dbs": []}

    def factory():
        db = FakeDB(state["sessions"], state["user"])
        state["dbs"].append(db)
        return db

    monkeypatch.setattr(meter_mod, "SessionLocal", factory)
    return state


class FakeManager:
    def __init__(self):
        self.broadcasts: list[tuple[int, dict]] = []
        self.stop_all_calls: list[tuple[int, str]] = []

    async def broadcast(self, sid: int, msg: dict) -> None:
        self.broadcasts.append((sid, msg))

    async def stop_all_for_user(self, user_id: int, reason: str) -> int:
        self.stop_all_calls.append((user_id, reason))
        return 0


@pytest.fixture
def patched_manager(monkeypatch):
    fake = FakeManager()
    import app.sessions.manager as mgr_mod

    monkeypatch.setattr(mgr_mod, "manager", fake)
    return fake


@pytest.fixture
def fast_sleep(monkeypatch):
    real_sleep = asyncio.sleep

    async def fake(s):
        await real_sleep(0)

    monkeypatch.setattr("app.sessions.meter.asyncio.sleep", fake)


# ============== ensure_running / stop_for_user ==============


@pytest.mark.asyncio
async def test_ensure_running_idempotent(
    patched_session_local, patched_manager, fast_sleep
):
    patched_session_local["sessions"] = []
    patched_session_local["user"] = FakeUser(1, 100)

    await ensure_running(1)
    await ensure_running(1)
    await ensure_running(1)

    await asyncio.sleep(0.01)

    assert patched_manager.stop_all_calls == []


@pytest.mark.asyncio
async def test_stop_for_user_cancels_task(patched_session_local, patched_manager):
    patched_session_local["sessions"] = [FakeSessionRow(11, 1)]
    patched_session_local["user"] = FakeUser(1, 100)

    await ensure_running(1)
    await stop_for_user(1)

    assert 1 not in meter_mod._user_meter_tasks


@pytest.mark.asyncio
async def test_stop_for_user_noop_when_no_task():
    await stop_for_user(999)


# ============== elapsed 累加 ==============


@pytest.mark.asyncio
async def test_meter_accumulates_elapsed_per_session(
    patched_session_local, patched_manager, monkeypatch
):
    sessions = [FakeSessionRow(11, 1), FakeSessionRow(12, 1)]
    patched_session_local["sessions"] = sessions
    patched_session_local["user"] = FakeUser(1, 1000)

    counter = {"n": 0}
    real_sleep = asyncio.sleep

    async def fake(s):
        counter["n"] += 1
        if counter["n"] > 3:
            raise asyncio.CancelledError()
        await real_sleep(0)

    monkeypatch.setattr("app.sessions.meter.asyncio.sleep", fake)

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    assert get_session_elapsed(11) == 3
    assert get_session_elapsed(12) == 3


@pytest.mark.asyncio
async def test_meter_exits_when_no_active(
    patched_session_local, patched_manager, fast_sleep
):
    patched_session_local["sessions"] = []
    patched_session_local["user"] = FakeUser(1, 100)

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    task = meter_mod._user_meter_tasks.get(1)
    if task is not None:
        await asyncio.sleep(0.05)
        assert task.done()


# ============== 余额耗尽路径 ==============


@pytest.mark.asyncio
async def test_meter_stops_all_when_balance_exhausted(
    patched_session_local, patched_manager, monkeypatch
):
    """balance=2, 1 active, 跑 ≥2 tick 后 charged=2, remaining=0 → stop。"""
    sessions = [FakeSessionRow(11, 1)]
    patched_session_local["sessions"] = sessions
    patched_session_local["user"] = FakeUser(1, 2)

    counter = {"n": 0}
    real_sleep = asyncio.sleep

    async def fake(s):
        counter["n"] += 1
        if counter["n"] > 5:
            raise asyncio.CancelledError()
        await real_sleep(0)

    monkeypatch.setattr("app.sessions.meter.asyncio.sleep", fake)

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    assert (1, "balance_zero") in patched_manager.stop_all_calls


# ============== broadcast ==============


@pytest.mark.asyncio
async def test_meter_broadcasts_balance_update(
    patched_session_local, patched_manager, monkeypatch
):
    sessions = [FakeSessionRow(11, 1)]
    patched_session_local["sessions"] = sessions
    patched_session_local["user"] = FakeUser(1, 100)

    counter = {"n": 0}
    real_sleep = asyncio.sleep

    async def fake(s):
        counter["n"] += 1
        if counter["n"] > 2:
            raise asyncio.CancelledError()
        await real_sleep(0)

    monkeypatch.setattr("app.sessions.meter.asyncio.sleep", fake)

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    update_msgs = [
        (sid, m)
        for sid, m in patched_manager.broadcasts
        if m["type"] == "balance_update"
    ]
    assert len(update_msgs) >= 1
    sid, m = update_msgs[0]
    assert sid == 11
    assert m["balance_seconds"] in (98, 99)


@pytest.mark.asyncio
async def test_meter_broadcasts_balance_low(
    patched_session_local, patched_manager, monkeypatch
):
    sessions = [FakeSessionRow(11, 1)]
    patched_session_local["sessions"] = sessions
    patched_session_local["user"] = FakeUser(1, 55)

    counter = {"n": 0}
    real_sleep = asyncio.sleep

    async def fake(s):
        counter["n"] += 1
        if counter["n"] > 6:
            raise asyncio.CancelledError()
        await real_sleep(0)

    monkeypatch.setattr("app.sessions.meter.asyncio.sleep", fake)

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    low_msgs = [
        m for sid, m in patched_manager.broadcasts if m["type"] == "balance_low"
    ]
    assert len(low_msgs) >= 1


# ============== flush_session_charge ==============


@pytest.mark.asyncio
async def test_flush_session_charge_writes_one_ledger(monkeypatch):
    meter_mod._session_elapsed[42] = 30

    grant_calls: list[dict] = []

    def fake_grant(**kw):
        grant_calls.append(kw)
        return 100

    monkeypatch.setattr(meter_mod, "grant", fake_grant)

    elapsed = await flush_session_charge(42, user_id=7)
    assert elapsed == 30
    assert get_session_elapsed(42) == 0

    assert len(grant_calls) == 1
    assert grant_calls[0]["delta_seconds"] == -30
    assert grant_calls[0]["reason"] == "session"
    assert grant_calls[0]["ref_id"] == 42
    assert grant_calls[0]["user_id"] == 7


@pytest.mark.asyncio
async def test_flush_session_charge_idempotent(monkeypatch):
    meter_mod._session_elapsed[42] = 10
    monkeypatch.setattr(meter_mod, "grant", lambda **kw: 100)

    e1 = await flush_session_charge(42, 7)
    e2 = await flush_session_charge(42, 7)
    assert e1 == 10
    assert e2 == 0


@pytest.mark.asyncio
async def test_flush_session_charge_zero_when_no_elapsed(monkeypatch):
    monkeypatch.setattr(
        meter_mod,
        "grant",
        lambda **kw: pytest.fail("grant should not run for 0 elapsed"),
    )
    e = await flush_session_charge(99, 7)
    assert e == 0


@pytest.mark.asyncio
async def test_flush_handles_grant_exception(monkeypatch):
    from fastapi import HTTPException

    meter_mod._session_elapsed[42] = 5

    def bad_grant(**kw):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "INSUFFICIENT_BALANCE", "message": "x"}},
        )

    monkeypatch.setattr(meter_mod, "grant", bad_grant)

    elapsed = await flush_session_charge(42, 7)
    assert elapsed == 5
    assert get_session_elapsed(42) == 0
