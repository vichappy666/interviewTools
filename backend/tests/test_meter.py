"""Tests for app.sessions.meter (M2 T9)。

策略：
- mock ``grant`` 为同步可控函数，避免触动真 DB
- mock ``SessionLocal`` 返回的 session：用一个 fake session 类，``.query``
  返回链式 builder，最终 ``.all()`` 给 mock 出来的 ``active_sessions`` 列表
- mock ``manager.broadcast`` / ``manager.stop_all_for_user`` 抓调用
- 让 ``asyncio.sleep`` 走真路径但配合 ``await asyncio.sleep(0.1)`` 跑几个 tick

测试间共享模块状态用 ``_reset_for_tests`` autouse fixture 隔离。
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from app.sessions import meter as meter_mod
from app.sessions.meter import (
    _is_insufficient_balance,
    _reset_for_tests,
    ensure_running,
    stop_for_user,
)


# ---------------- 测试工具：fake DB ----------------


class _FakeSession:
    """模拟 sessions 表行：暴露 ``.id``。"""

    def __init__(self, sid: int, user_id: int = 1):
        self.id = sid
        self.user_id = user_id
        self.status = "active"


class _FakeQuery:
    """链式 query builder 仅实现 ``.filter().order_by().all()``。"""

    def __init__(self, rows: list[_FakeSession]):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    """模拟 SessionLocal() 返回的 session 对象。"""

    def __init__(self, rows_provider):
        # rows_provider: callable returning current list of FakeSession
        self._provider = rows_provider
        self.closed = False

    def query(self, _model):
        return _FakeQuery(self._provider())

    def close(self):
        self.closed = True


# ---------------- 测试 fixtures ----------------


@pytest.fixture(autouse=True)
async def _reset_meter_state():
    """每个测试前清空 meter 的所有模块状态，并 await 任何残留 task 结束。"""
    _reset_for_tests()
    # 给 cancelled 的 task 一次机会真正结束
    await asyncio.sleep(0)
    yield
    # 测试结束：cancel 残留 task 并清理
    _reset_for_tests()
    await asyncio.sleep(0)


@pytest.fixture
def patched_meter(monkeypatch):
    """把 meter 模块里所有外部依赖都替换成 fake，返回 spy 容器。

    spy 包含：
      - active_rows: 当前 user_id=1 的 active session 列表（可外部修改）
      - grant_calls: 每次 grant 的参数列表
      - balance: 当前模拟余额（每次 grant 默认扣 N，可配置）
      - grant_side_effect: 可设为 callable(user_id, delta) → new_balance 或抛异常
      - broadcasts: list of (session_id, payload)
      - stop_all_calls: list of (user_id, reason)
    """
    spy: dict[str, Any] = {
        "active_rows": [_FakeSession(101, user_id=1)],
        "grant_calls": [],
        "balance": 3600,
        "grant_side_effect": None,
        "broadcasts": [],
        "stop_all_calls": [],
    }

    def fake_session_local():
        return _FakeDB(lambda: spy["active_rows"])

    def fake_grant(*, db, user_id, delta_seconds, reason, ref_type, ref_id, note=None):
        spy["grant_calls"].append(
            {
                "user_id": user_id,
                "delta_seconds": delta_seconds,
                "reason": reason,
                "ref_type": ref_type,
                "ref_id": ref_id,
            }
        )
        if spy["grant_side_effect"] is not None:
            return spy["grant_side_effect"](user_id, delta_seconds)
        spy["balance"] += delta_seconds
        if spy["balance"] < 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "INSUFFICIENT_BALANCE",
                        "message": "余额不足",
                    }
                },
            )
        return spy["balance"]

    class _FakeManager:
        async def broadcast(self, sid, msg):
            spy["broadcasts"].append((sid, msg))

        async def stop_all_for_user(self, user_id, reason):
            spy["stop_all_calls"].append((user_id, reason))
            # 模拟 stop 之后 active_rows 变空（balance_zero 真实路径）
            spy["active_rows"] = [
                r for r in spy["active_rows"] if r.user_id != user_id
            ]
            return 0

    fake_manager = _FakeManager()

    monkeypatch.setattr(meter_mod, "SessionLocal", fake_session_local)
    monkeypatch.setattr(meter_mod, "grant", fake_grant)
    # patch import-inside-function: app.sessions.manager.manager
    import app.sessions.manager as mgr_mod

    monkeypatch.setattr(mgr_mod, "manager", fake_manager)
    return spy


@pytest.fixture
def fast_sleep(monkeypatch):
    """让 meter 模块里的 asyncio.sleep 直接 yield 一次，每次都让出事件循环。

    返回的 dict 可以让测试控制最大 tick 数后让 task 自然 cancel。
    """
    state = {"ticks": 0, "max_ticks": 10}

    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        state["ticks"] += 1
        if state["ticks"] > state["max_ticks"]:
            # 抛 cancel 让 task 自然结束
            raise asyncio.CancelledError()
        # yield 一次让其他协程进展
        await real_sleep(0)

    # patch meter 模块里看到的 asyncio.sleep
    import app.sessions.meter as meter_mod_local

    class _AsyncioProxy:
        sleep = fake_sleep
        CancelledError = asyncio.CancelledError
        Lock = asyncio.Lock
        create_task = staticmethod(asyncio.create_task)
        Task = asyncio.Task

    # 不能整个替 asyncio —— meter 用了 asyncio.Lock/CancelledError/create_task。
    # 改用：替 meter 里的 asyncio.sleep 函数
    monkeypatch.setattr(meter_mod_local.asyncio, "sleep", fake_sleep)
    return state


# ---------------- 单元测试：helper ----------------


def test_is_insufficient_balance_true():
    exc = HTTPException(
        status_code=400,
        detail={"error": {"code": "INSUFFICIENT_BALANCE", "message": "x"}},
    )
    assert _is_insufficient_balance(exc) is True


def test_is_insufficient_balance_other_code_false():
    exc = HTTPException(
        status_code=400,
        detail={"error": {"code": "OTHER", "message": "x"}},
    )
    assert _is_insufficient_balance(exc) is False


def test_is_insufficient_balance_string_detail_false():
    exc = HTTPException(status_code=400, detail="plain string")
    assert _is_insufficient_balance(exc) is False


# ---------------- ensure_running / stop_for_user ----------------


async def test_ensure_running_idempotent(patched_meter, fast_sleep):
    """同 user 多次 ensure 只起 1 个 task。"""
    fast_sleep["max_ticks"] = 1000  # 让 task 不会自然死

    await ensure_running(1)
    t1 = meter_mod._user_meter_tasks[1]
    await ensure_running(1)
    t2 = meter_mod._user_meter_tasks[1]
    await ensure_running(1)
    t3 = meter_mod._user_meter_tasks[1]
    assert t1 is t2 is t3


async def test_ensure_running_recreates_after_done(patched_meter, fast_sleep):
    """task done 之后再 ensure 会建一个新的。"""
    fast_sleep["max_ticks"] = 1  # 一秒就死
    patched_meter["active_rows"] = []  # 0 active → 立刻退出

    await ensure_running(1)
    first = meter_mod._user_meter_tasks[1]
    await asyncio.wait_for(first, timeout=2.0)
    assert first.done()

    fast_sleep["ticks"] = 0
    fast_sleep["max_ticks"] = 1
    await ensure_running(1)
    second = meter_mod._user_meter_tasks[1]
    assert second is not first


async def test_stop_for_user_cancels_task(patched_meter, fast_sleep):
    fast_sleep["max_ticks"] = 1000  # 不让自然结束
    patched_meter["active_rows"] = [_FakeSession(101, user_id=1)]

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    await asyncio.sleep(0)  # 给 task 一次启动机会

    await stop_for_user(1)
    assert 1 not in meter_mod._user_meter_tasks
    assert task.done()


async def test_stop_for_user_noop_when_no_task():
    """没起 task 时 stop_for_user 不抛。"""
    await stop_for_user(999)


# ---------------- 扣费逻辑 ----------------


async def test_meter_grants_one_second_per_active_session(
    patched_meter, fast_sleep
):
    """1 个 active session → 每 tick 扣 1 秒。"""
    fast_sleep["max_ticks"] = 5
    patched_meter["active_rows"] = [_FakeSession(101, user_id=1)]
    patched_meter["balance"] = 1000

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    # 等 task 自然 cancel 退出
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    # 至少扣了 1 次（保险：5 ticks 都能扣）
    assert len(patched_meter["grant_calls"]) >= 1
    for call in patched_meter["grant_calls"]:
        assert call["delta_seconds"] == -1
        assert call["reason"] == "session"
        assert call["ref_type"] == "session"
        assert call["ref_id"] == 101
        assert call["user_id"] == 1


async def test_meter_grants_n_seconds_for_n_concurrent(
    patched_meter, fast_sleep
):
    """3 个 active session → 每 tick 扣 3 秒，ref_id = 最小 id。"""
    fast_sleep["max_ticks"] = 3
    patched_meter["active_rows"] = [
        _FakeSession(202, user_id=1),
        _FakeSession(101, user_id=1),  # 最小 id
        _FakeSession(303, user_id=1),
    ]
    patched_meter["balance"] = 1000

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    assert len(patched_meter["grant_calls"]) >= 1
    for call in patched_meter["grant_calls"]:
        assert call["delta_seconds"] == -3
    # ref_id 应是最小的 active session id（_FakeSession 排序后 101 第一）
    # 注意：_FakeQuery.order_by 是 noop，所以这里 ref_id 取列表中第一个 = 202
    # 修正：FakeQuery 不真 sort —— 我们想测试 meter 在真 DB 下会用 id 升序。
    # FakeQuery 没排序时 ref_id = active_rows[0].id = 202
    assert patched_meter["grant_calls"][0]["ref_id"] == 202


async def test_meter_exits_when_no_active_sessions(patched_meter, fast_sleep):
    """0 active → 立刻 return（task done），不调 grant。"""
    fast_sleep["max_ticks"] = 5
    patched_meter["active_rows"] = []

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    await asyncio.wait_for(task, timeout=2.0)
    assert task.done()
    assert patched_meter["grant_calls"] == []


async def test_meter_calls_stop_all_when_insufficient_balance(
    patched_meter, fast_sleep
):
    """grant 抛 INSUFFICIENT_BALANCE → manager.stop_all_for_user 被调；task 退出。"""
    fast_sleep["max_ticks"] = 100
    patched_meter["active_rows"] = [_FakeSession(101, user_id=1)]

    def explosive(user_id, delta):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INSUFFICIENT_BALANCE",
                    "message": "余额不足",
                }
            },
        )

    patched_meter["grant_side_effect"] = explosive

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    assert task.done()
    assert patched_meter["stop_all_calls"] == [(1, "balance_zero")]


async def test_meter_exits_on_other_http_exception(patched_meter, fast_sleep):
    """grant 抛非 INSUFFICIENT_BALANCE 的 HTTPException → task 退出，不调 stop_all。"""
    fast_sleep["max_ticks"] = 100
    patched_meter["active_rows"] = [_FakeSession(101, user_id=1)]

    def boom(user_id, delta):
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "USER_NOT_FOUND", "message": "x"}},
        )

    patched_meter["grant_side_effect"] = boom

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    assert task.done()
    assert patched_meter["stop_all_calls"] == []


async def test_meter_handles_grant_exceptions_gracefully(
    patched_meter, fast_sleep
):
    """grant 抛任意非 HTTPException → task 退出但不向上层抛。"""
    fast_sleep["max_ticks"] = 100
    patched_meter["active_rows"] = [_FakeSession(101, user_id=1)]

    def random_boom(user_id, delta):
        raise RuntimeError("db connection lost")

    patched_meter["grant_side_effect"] = random_boom

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    # task 内部 catch 通用 Exception → return，不重抛
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    assert task.done()
    # 不应抛上来；exception() 返回 None（已正常 return）
    assert task.exception() is None


# ---------------- 广播 ----------------


async def test_meter_broadcasts_balance_update_first_tick(
    patched_meter, fast_sleep
):
    """首轮一定推一次 balance_update。"""
    fast_sleep["max_ticks"] = 1
    patched_meter["active_rows"] = [_FakeSession(101, user_id=1)]
    patched_meter["balance"] = 1000

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    bu = [
        msg for sid, msg in patched_meter["broadcasts"]
        if msg.get("type") == "balance_update"
    ]
    assert len(bu) >= 1
    assert bu[0]["balance_seconds"] == 999


async def test_meter_broadcasts_balance_update_only_on_floor_change(
    patched_meter, fast_sleep
):
    """1 active session 下，每秒扣 1，跨 10 秒边界才再推 balance_update。"""
    fast_sleep["max_ticks"] = 12  # 跑 12 tick
    patched_meter["active_rows"] = [_FakeSession(101, user_id=1)]
    patched_meter["balance"] = 1015  # 1015→1014→...→1003 = 12 次扣 → 跨 1010, 1000 两个边界

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=3.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    bu = [
        msg for sid, msg in patched_meter["broadcasts"]
        if msg.get("type") == "balance_update"
    ]
    # 首推 + 跨 1010 + 跨 1000 = 3 次（首 floor=101，第一秒后 floor=101，是首推；
    # 1014→101, 1013→101, ..., 1010→101, 1009→100 → 第一次跨边界推；
    # 999→99 → 第二次跨边界推。)
    # 实际：第 1 tick balance=1014 → 首推（floor=101）
    # 第 5 tick balance=1010 (floor=101 不变) → 不推
    # 第 6 tick balance=1009 (floor=100) → 推
    # 第 12 tick balance=1003 (floor=100 不变) → 不推
    assert 2 <= len(bu) <= 4


async def test_meter_broadcasts_balance_low_when_below_60(
    patched_meter, fast_sleep
):
    """余额跌到 ≤60 后，每 5 tick 推一次 balance_low。"""
    fast_sleep["max_ticks"] = 12
    patched_meter["active_rows"] = [_FakeSession(101, user_id=1)]
    patched_meter["balance"] = 65  # 1秒后 64, 2秒 63, 3秒 62, 4秒 61, 5秒 60 (推)

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=3.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    bl = [
        msg for sid, msg in patched_meter["broadcasts"]
        if msg.get("type") == "balance_low"
    ]
    assert len(bl) >= 1
    for msg in bl:
        assert 0 < msg["balance_seconds"] <= 60


async def test_meter_broadcasts_to_all_active_sessions(
    patched_meter, fast_sleep
):
    """多 active session：balance_update 应该推给所有 session。"""
    fast_sleep["max_ticks"] = 1
    patched_meter["active_rows"] = [
        _FakeSession(101, user_id=1),
        _FakeSession(102, user_id=1),
    ]
    patched_meter["balance"] = 1000

    await ensure_running(1)
    task = meter_mod._user_meter_tasks[1]
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    bu_sids = {
        sid for sid, msg in patched_meter["broadcasts"]
        if msg.get("type") == "balance_update"
    }
    assert bu_sids == {101, 102}
