"""Tests for app.sessions.manager (M2 T4)。

用 fake WebSocket 替代真 ws，避免起 FastAPI server。fixture 自动清空
全局 manager，避免跨测试串扰。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional

import pytest

from app.sessions.manager import (
    SessionManager,
    SessionRuntime,
    StateSnapshot,
    manager,
)


# ---------------- Fake WebSocket ----------------


class FakeWS:
    """轻量 mock，仅实现 manager 用到的 send_text/close。"""

    def __init__(self, *, fail_on_send: bool = False, fail_on_close: bool = False):
        self.sent: list[str] = []
        self.closed_with_code: Optional[int] = None
        self.fail_on_send = fail_on_send
        self.fail_on_close = fail_on_close

    async def send_text(self, payload: str) -> None:
        if self.fail_on_send:
            raise RuntimeError("fake ws send failure")
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        if self.fail_on_close:
            raise RuntimeError("fake ws close failure")
        self.closed_with_code = code


# ---------------- Fixtures ----------------


@pytest.fixture(autouse=True)
def _reset_manager():
    """每个测试前后清空全局 manager.sessions，避免相互影响。"""
    manager.sessions.clear()
    yield
    manager.sessions.clear()


@pytest.fixture
def started_at() -> datetime:
    return datetime(2026, 4, 29, 10, 0, 0)


# ---------------- 注册 / 查询 ----------------


async def test_register_and_get(started_at):
    runtime = await manager.register_session(1, user_id=42, started_at=started_at)
    assert isinstance(runtime, SessionRuntime)
    assert runtime.id == 1
    assert runtime.user_id == 42
    assert runtime.started_at == started_at
    assert runtime.connections == set()
    assert runtime.asr_client is None
    assert runtime.meter_task is None
    assert isinstance(runtime.state_snapshot, StateSnapshot)

    # get 同步读
    got = manager.get(1)
    assert got is runtime
    assert manager.get(999) is None


async def test_register_is_idempotent(started_at):
    a = await manager.register_session(7, user_id=1, started_at=started_at)
    b = await manager.register_session(7, user_id=1, started_at=started_at)
    assert a is b
    assert len(manager.sessions) == 1


async def test_list_for_user(started_at):
    await manager.register_session(1, user_id=10, started_at=started_at)
    await manager.register_session(2, user_id=10, started_at=started_at)
    await manager.register_session(3, user_id=20, started_at=started_at)
    a = manager.list_for_user(10)
    b = manager.list_for_user(20)
    c = manager.list_for_user(99)
    assert {r.id for r in a} == {1, 2}
    assert {r.id for r in b} == {3}
    assert c == []


# ---------------- 连接管理 ----------------


async def test_add_connection_unknown_session_raises(started_at):
    ws = FakeWS()
    with pytest.raises(KeyError):
        await manager.add_connection(123, ws)


async def test_add_connection_returns_runtime_with_snapshot(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    ws1 = FakeWS()
    ws2 = FakeWS()

    r1 = await manager.add_connection(1, ws1)
    r2 = await manager.add_connection(1, ws2)
    assert r1 is r2
    assert r1.connections == {ws1, ws2}
    # snapshot 默认是空的
    assert r1.state_snapshot.transcript_finals == []
    assert r1.state_snapshot.transcript_partial == ""
    assert r1.state_snapshot.questions == []
    assert r1.state_snapshot.current_answer is None


async def test_remove_connection_decrements_count(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    ws1, ws2 = FakeWS(), FakeWS()
    await manager.add_connection(1, ws1)
    await manager.add_connection(1, ws2)

    remaining = await manager.remove_connection(1, ws1)
    assert remaining == 1
    assert ws1 not in manager.get(1).connections
    assert ws2 in manager.get(1).connections

    # 再移除一次（已经不在）— 不抛、返回当前剩余
    remaining = await manager.remove_connection(1, ws1)
    assert remaining == 1


async def test_remove_connection_unknown_session_returns_zero():
    n = await manager.remove_connection(999, FakeWS())
    assert n == 0


# ---------------- broadcast ----------------


async def test_broadcast_sends_to_all_connections(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    ws1, ws2 = FakeWS(), FakeWS()
    await manager.add_connection(1, ws1)
    await manager.add_connection(1, ws2)

    await manager.broadcast(1, {"type": "hello", "data": "你好"})

    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1
    # ensure_ascii=False 保留中文
    msg = json.loads(ws1.sent[0])
    assert msg == {"type": "hello", "data": "你好"}
    assert "你好" in ws1.sent[0]


async def test_broadcast_one_failing_ws_does_not_block_others(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    bad = FakeWS(fail_on_send=True)
    good = FakeWS()
    await manager.add_connection(1, bad)
    await manager.add_connection(1, good)

    # 不应抛
    await manager.broadcast(1, {"type": "ping"})

    assert good.sent == [json.dumps({"type": "ping"}, ensure_ascii=False)]
    # 失败的 ws 不会从 connections 里被立即移除（让 disconnect handler 清理）
    assert bad in manager.get(1).connections


async def test_broadcast_unknown_session_is_silent():
    # 不抛
    await manager.broadcast(999, {"type": "noop"})


# ---------------- stop ----------------


async def test_stop_clears_runtime_and_closes_ws(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    ws1, ws2 = FakeWS(), FakeWS()
    await manager.add_connection(1, ws1)
    await manager.add_connection(1, ws2)

    await manager.stop(1, reason="user_stop")

    assert manager.get(1) is None
    # 收到 session_ended 广播
    assert any(
        json.loads(p) == {"type": "session_ended", "reason": "user_stop"}
        for p in ws1.sent
    )
    assert any(
        json.loads(p) == {"type": "session_ended", "reason": "user_stop"}
        for p in ws2.sent
    )
    # ws 都被 close
    assert ws1.closed_with_code == 1000
    assert ws2.closed_with_code == 1000


async def test_stop_idempotent_for_missing_session():
    # 不抛
    await manager.stop(12345, reason="anything")


async def test_stop_cancels_meter_task(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    runtime = manager.get(1)

    cancelled = asyncio.Event()

    async def long_task():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    runtime.meter_task = asyncio.create_task(long_task())
    # 让 task 真的开始执行
    await asyncio.sleep(0)

    await manager.stop(1, reason="balance_zero")
    # 给 event loop 一次机会运行被 cancel 的协程
    await asyncio.sleep(0)
    assert cancelled.is_set()


async def test_stop_calls_asr_client_close(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    runtime = manager.get(1)

    closed = asyncio.Event()

    class FakeASR:
        async def close(self):
            closed.set()

    runtime.asr_client = FakeASR()
    await manager.stop(1, reason="user_stop")
    assert closed.is_set()


async def test_stop_swallows_asr_close_error(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    runtime = manager.get(1)

    class BadASR:
        async def close(self):
            raise RuntimeError("boom")

    runtime.asr_client = BadASR()
    # 不应抛
    await manager.stop(1, reason="user_stop")
    assert manager.get(1) is None


async def test_stop_swallows_ws_close_error(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    bad_ws = FakeWS(fail_on_close=True)
    good_ws = FakeWS()
    await manager.add_connection(1, bad_ws)
    await manager.add_connection(1, good_ws)

    # 不应抛；good_ws 仍然被 close
    await manager.stop(1, reason="user_stop")
    assert good_ws.closed_with_code == 1000


async def test_stop_all_for_user(started_at):
    await manager.register_session(1, user_id=10, started_at=started_at)
    await manager.register_session(2, user_id=10, started_at=started_at)
    await manager.register_session(3, user_id=20, started_at=started_at)

    n = await manager.stop_all_for_user(10, reason="balance_zero")
    assert n == 2
    assert manager.get(1) is None
    assert manager.get(2) is None
    # 别的用户不受影响
    assert manager.get(3) is not None


async def test_stop_all_for_user_no_sessions_returns_zero():
    n = await manager.stop_all_for_user(99, reason="noop")
    assert n == 0


# ---------------- State snapshot 更新 ----------------


async def test_update_partial_overrides(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    await manager.update_partial(1, "你好")
    assert manager.get(1).state_snapshot.transcript_partial == "你好"
    await manager.update_partial(1, "你好世界")
    assert manager.get(1).state_snapshot.transcript_partial == "你好世界"


async def test_append_final_pushes_and_clears_partial(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    await manager.update_partial(1, "未结束的 partial")
    await manager.append_final(1, "第一段已 finalize", 1.5)
    await manager.append_final(1, "第二段", 3.0)

    snap = manager.get(1).state_snapshot
    assert snap.transcript_finals == [
        {"text": "第一段已 finalize", "ts": 1.5},
        {"text": "第二段", "ts": 3.0},
    ]
    # finalize 后 partial 清空
    assert snap.transcript_partial == ""


async def test_append_question(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    await manager.append_question(1, qa_id=11, text="自我介绍一下", asked_at=10.0)
    await manager.append_question(1, qa_id=12, text="为什么离职", asked_at=42.5)
    qs = manager.get(1).state_snapshot.questions
    assert qs == [
        {"qa_id": 11, "text": "自我介绍一下", "asked_at": 10.0},
        {"qa_id": 12, "text": "为什么离职", "asked_at": 42.5},
    ]


async def test_update_answer_chunk_appends_per_segment(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)

    await manager.update_answer_chunk(1, qa_id=11, segment="key_points", text="• 要点1\n")
    await manager.update_answer_chunk(1, qa_id=11, segment="key_points", text="• 要点2")
    await manager.update_answer_chunk(1, qa_id=11, segment="script", text="您好，")
    await manager.update_answer_chunk(1, qa_id=11, segment="script", text="我的看法是...")
    await manager.update_answer_chunk(1, qa_id=11, segment="full", text="完整段落。")

    ans = manager.get(1).state_snapshot.current_answer
    assert ans == {
        "qa_id": 11,
        "sections": {
            "key_points": {"text": "• 要点1\n• 要点2", "state": "streaming"},
            "script": {"text": "您好，我的看法是...", "state": "streaming"},
            "full": {"text": "完整段落。", "state": "streaming"},
        },
    }


async def test_update_answer_chunk_resets_on_new_qa_id(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    await manager.update_answer_chunk(1, qa_id=11, segment="full", text="老回答")
    # 切换到新 qa_id：current_answer 重置
    await manager.update_answer_chunk(1, qa_id=12, segment="full", text="新回答开头")

    ans = manager.get(1).state_snapshot.current_answer
    assert ans == {
        "qa_id": 12,
        "sections": {
            "full": {"text": "新回答开头", "state": "streaming"},
        },
    }


async def test_update_answer_chunk_invalid_segment(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    with pytest.raises(ValueError):
        await manager.update_answer_chunk(1, qa_id=11, segment="bogus", text="x")


async def test_finalize_answer_clears_current(started_at):
    await manager.register_session(1, user_id=42, started_at=started_at)
    await manager.update_answer_chunk(1, qa_id=11, segment="full", text="hi")
    assert manager.get(1).state_snapshot.current_answer is not None
    await manager.finalize_answer(1)
    assert manager.get(1).state_snapshot.current_answer is None


async def test_state_updates_on_unknown_session_are_silent():
    # 各种 update 在 session 不存在时应静默 no-op，不抛
    await manager.update_partial(999, "x")
    await manager.append_final(999, "x", 0.0)
    await manager.append_question(999, qa_id=1, text="x", asked_at=0.0)
    await manager.update_answer_chunk(999, qa_id=1, segment="full", text="x")
    await manager.finalize_answer(999)


# ---------------- 单例性质 ----------------


async def test_module_level_singleton_is_shared():
    """import 出来的 manager 与类实例化的不同。"""
    fresh = SessionManager()
    assert fresh is not manager
    # 但 module-level 的 manager 在不同 import 点应该是同一个对象
    from app.sessions.manager import manager as m2
    assert m2 is manager
