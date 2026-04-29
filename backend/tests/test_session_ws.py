"""Tests for app.sessions.ws (M2 T8) — WebSocket /ws/session/{id}。

策略：
- 优先单测 ``_handle_text_message`` / ``_run_ask`` / ``_asr_forward`` 三个内部 helper，
  完全脱离 ws server 与 FastAPI TestClient。
- 集成测试用 :class:`fastapi.testclient.TestClient.websocket_connect`：
  patch ``app.sessions.ws.SessionLocal`` 指向同一份 in-memory sqlite，patch
  ``VolcengineASRClient`` / ``LLMService`` 为 fake，验证：
    * 鉴权 close code（4401 / 4403 / 4404 / 4410）
    * 成功握手后立即收到 snapshot
    * ping → pong / 未知 type → error / bad json → error
    * stop → DB 标 ended + manager.stop 被触发
    * 断线时 remove_connection 被调

需要 patch SessionLocal 是因为 ws.py 内部直接 ``from app.db import SessionLocal``
后调 ``SessionLocal()``，FastAPI dependency override 帮不上忙。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Optional

import pytest

from app.auth.security import hash_password, make_admin_token, make_user_token
from app.models.session import Session as SessionModel
from app.models.session_qa import SessionQA
from app.models.user import User
from app.sessions import ws as ws_module
from app.sessions.manager import SessionManager, manager


# ---------------- Fakes ----------------


class FakeWS:
    """轻量 ws 替身，仅实现 send_text / receive / close / accept。"""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed_with_code: Optional[int] = None
        self.accepted = False
        self._inbound: asyncio.Queue = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.closed_with_code = code

    async def receive(self) -> dict:
        return await self._inbound.get()

    # Test-side helpers
    async def feed_text(self, text: str) -> None:
        await self._inbound.put({"type": "websocket.receive", "text": text})

    async def feed_bytes(self, data: bytes) -> None:
        await self._inbound.put({"type": "websocket.receive", "bytes": data})

    async def feed_disconnect(self) -> None:
        await self._inbound.put({"type": "websocket.disconnect"})

    def sent_messages(self) -> list[dict]:
        return [json.loads(p) for p in self.sent]


class FakeASRClient:
    """供 _asr_forward / _ensure_asr_started 测试用。"""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.fed: list[bytes] = []
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def feed_pcm(self, frame: bytes) -> None:
        self.fed.append(frame)

    async def close(self) -> None:
        self.closed = True

    async def stream_results(self):
        # 默认空流，立即结束
        if False:  # pragma: no cover
            yield None


# ---------------- Fixtures ----------------


@pytest.fixture(autouse=True)
def _reset_manager():
    manager.sessions.clear()
    yield
    manager.sessions.clear()


@pytest.fixture
def patch_session_local(monkeypatch, db_session):
    """让 ws.py 内部 SessionLocal() 拿到测试的 in-memory sqlite 同一连接。"""
    bind = db_session.get_bind()

    class _SL:
        def __call__(self) -> Any:
            from sqlalchemy.orm import sessionmaker
            return sessionmaker(bind=bind, autoflush=False, autocommit=False)()

    sl = _SL()
    monkeypatch.setattr(ws_module, "SessionLocal", sl)
    # question_handler 不直接用 SessionLocal（它接受 db 参数），无需 patch
    return sl


@pytest.fixture
def make_user(db_session):
    def _make(name: str = "alice", balance: int = 3600) -> User:
        u = User(
            username=name,
            password_hash=hash_password("secret123"),
            balance_seconds=balance,
        )
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        return u
    return _make


@pytest.fixture
def make_session(db_session):
    def _make(user_id: int, status: str = "active") -> SessionModel:
        s = SessionModel(user_id=user_id, status=status, total_seconds=0)
        db_session.add(s)
        db_session.commit()
        db_session.refresh(s)
        return s
    return _make


# ---------------- Auth / handshake 单元测试 ----------------


async def test_invalid_token_closes_4401(patch_session_local, make_user):
    fw = FakeWS()
    await ws_module.session_ws(fw, session_id=1, token="not-a-jwt")
    assert fw.closed_with_code == ws_module.CLOSE_AUTH
    assert not fw.accepted


async def test_admin_token_rejected_4403(patch_session_local, make_user):
    fw = FakeWS()
    token = make_admin_token(7)
    await ws_module.session_ws(fw, session_id=1, token=token)
    assert fw.closed_with_code == ws_module.CLOSE_FORBIDDEN
    assert not fw.accepted


async def test_session_not_found_4404(patch_session_local, make_user):
    user = make_user()
    fw = FakeWS()
    token = make_user_token(user.id)
    await ws_module.session_ws(fw, session_id=99999, token=token)
    assert fw.closed_with_code == ws_module.CLOSE_NOT_FOUND
    assert not fw.accepted


async def test_session_owned_by_other_user_4403(
    patch_session_local, make_user, make_session
):
    a = make_user("alice")
    b = make_user("bob")
    sess = make_session(a.id)
    fw = FakeWS()
    token = make_user_token(b.id)
    await ws_module.session_ws(fw, session_id=sess.id, token=token)
    assert fw.closed_with_code == ws_module.CLOSE_FORBIDDEN


async def test_ended_session_rejected_4410(
    patch_session_local, make_user, make_session
):
    user = make_user()
    sess = make_session(user.id, status="ended")
    fw = FakeWS()
    token = make_user_token(user.id)
    await ws_module.session_ws(fw, session_id=sess.id, token=token)
    assert fw.closed_with_code == ws_module.CLOSE_GONE


# ---------------- 主收发循环：snapshot / ping / unknown / bad json / stop ----------------


async def _start_ws_loop(monkeypatch, ws_module_, fake_ws, session_id, token):
    """启动 session_ws 作为后台 task；用 fake ASR 防止启 ASR 进程。"""
    monkeypatch.setattr(ws_module_, "VolcengineASRClient", FakeASRClient)
    task = asyncio.create_task(
        ws_module_.session_ws(fake_ws, session_id=session_id, token=token)
    )
    return task


async def _wait_for_snapshot(fake_ws: FakeWS, timeout: float = 1.0) -> dict:
    """轮询直到 fake_ws.sent 出现 snapshot。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for raw in fake_ws.sent:
            msg = json.loads(raw)
            if msg.get("type") == "snapshot":
                return msg
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"timeout waiting for snapshot; sent={fake_ws.sent}"
    )


async def test_accept_and_snapshot_pushed(
    patch_session_local, monkeypatch, make_user, make_session
):
    user = make_user()
    sess = make_session(user.id)
    token = make_user_token(user.id)
    fw = FakeWS()

    task = await _start_ws_loop(monkeypatch, ws_module, fw, sess.id, token)
    try:
        snap = await _wait_for_snapshot(fw)
        assert fw.accepted
        assert snap["transcript_finals"] == []
        assert snap["transcript_partial"] == ""
        assert snap["questions"] == []
        assert snap["current_answer"] is None

        # session 已注册到 manager
        runtime = manager.get(sess.id)
        assert runtime is not None
        assert fw in runtime.connections
    finally:
        await fw.feed_disconnect()
        await asyncio.wait_for(task, timeout=1.0)


async def test_ping_pong(
    patch_session_local, monkeypatch, make_user, make_session
):
    user = make_user()
    sess = make_session(user.id)
    token = make_user_token(user.id)
    fw = FakeWS()

    task = await _start_ws_loop(monkeypatch, ws_module, fw, sess.id, token)
    try:
        await _wait_for_snapshot(fw)
        await fw.feed_text(json.dumps({"type": "ping"}))
        # 等 pong
        for _ in range(50):
            if any(json.loads(p).get("type") == "pong" for p in fw.sent):
                break
            await asyncio.sleep(0.01)
        assert any(json.loads(p).get("type") == "pong" for p in fw.sent)
    finally:
        await fw.feed_disconnect()
        await asyncio.wait_for(task, timeout=1.0)


async def test_unknown_type_returns_error(
    patch_session_local, monkeypatch, make_user, make_session
):
    user = make_user()
    sess = make_session(user.id)
    token = make_user_token(user.id)
    fw = FakeWS()

    task = await _start_ws_loop(monkeypatch, ws_module, fw, sess.id, token)
    try:
        await _wait_for_snapshot(fw)
        await fw.feed_text(json.dumps({"type": "bogus"}))
        for _ in range(50):
            errs = [
                json.loads(p)
                for p in fw.sent
                if json.loads(p).get("type") == "error"
            ]
            if errs:
                break
            await asyncio.sleep(0.01)
        msgs = [json.loads(p) for p in fw.sent]
        err = next(m for m in msgs if m.get("type") == "error")
        assert err["code"] == "UNKNOWN_TYPE"
    finally:
        await fw.feed_disconnect()
        await asyncio.wait_for(task, timeout=1.0)


async def test_bad_json_returns_error(
    patch_session_local, monkeypatch, make_user, make_session
):
    user = make_user()
    sess = make_session(user.id)
    token = make_user_token(user.id)
    fw = FakeWS()

    task = await _start_ws_loop(monkeypatch, ws_module, fw, sess.id, token)
    try:
        await _wait_for_snapshot(fw)
        await fw.feed_text("not json {")
        for _ in range(50):
            if any(json.loads(p).get("type") == "error" for p in fw.sent):
                break
            await asyncio.sleep(0.01)
        msgs = [json.loads(p) for p in fw.sent]
        err = next(m for m in msgs if m.get("type") == "error")
        assert err["code"] == "BAD_JSON"
    finally:
        await fw.feed_disconnect()
        await asyncio.wait_for(task, timeout=1.0)


async def test_stop_marks_session_ended_in_db(
    patch_session_local, monkeypatch, make_user, make_session, db_session
):
    user = make_user()
    sess = make_session(user.id)
    token = make_user_token(user.id)
    fw = FakeWS()

    task = await _start_ws_loop(monkeypatch, ws_module, fw, sess.id, token)
    try:
        await _wait_for_snapshot(fw)
        await fw.feed_text(json.dumps({"type": "stop"}))
        await asyncio.wait_for(task, timeout=1.0)
    finally:
        if not task.done():
            task.cancel()

    # 等 manager.stop 后台 task 跑完
    for _ in range(50):
        db_session.expire_all()
        row = (
            db_session.query(SessionModel)
            .filter(SessionModel.id == sess.id)
            .one()
        )
        if row.status == "ended":
            break
        await asyncio.sleep(0.01)
    db_session.expire_all()
    row = (
        db_session.query(SessionModel)
        .filter(SessionModel.id == sess.id)
        .one()
    )
    assert row.status == "ended"
    assert row.end_reason == "user_stop"
    assert row.ended_at is not None


async def test_binary_forwards_to_asr(
    patch_session_local, monkeypatch, make_user, make_session
):
    """二进制帧应转给 runtime.asr_client.feed_pcm。"""
    user = make_user()
    sess = make_session(user.id)
    token = make_user_token(user.id)
    fw = FakeWS()

    task = await _start_ws_loop(monkeypatch, ws_module, fw, sess.id, token)
    try:
        await _wait_for_snapshot(fw)
        runtime = manager.get(sess.id)
        assert runtime is not None
        assert isinstance(runtime.asr_client, FakeASRClient)

        await fw.feed_bytes(b"\x00\x01\x02")
        await fw.feed_bytes(b"\x03\x04\x05")
        # 等 ASR 收到
        for _ in range(50):
            if len(runtime.asr_client.fed) >= 2:
                break
            await asyncio.sleep(0.01)
        assert runtime.asr_client.fed == [b"\x00\x01\x02", b"\x03\x04\x05"]
    finally:
        await fw.feed_disconnect()
        await asyncio.wait_for(task, timeout=1.0)


async def test_disconnect_calls_remove_connection(
    patch_session_local, monkeypatch, make_user, make_session
):
    """断线后 finally 应 remove_connection。"""
    user = make_user()
    sess = make_session(user.id)
    token = make_user_token(user.id)
    fw = FakeWS()

    task = await _start_ws_loop(monkeypatch, ws_module, fw, sess.id, token)
    try:
        await _wait_for_snapshot(fw)
        runtime = manager.get(sess.id)
        assert fw in runtime.connections

        await fw.feed_disconnect()
        await asyncio.wait_for(task, timeout=1.0)

        # session 仍在 manager（不自动停），但 fw 被移除
        runtime_after = manager.get(sess.id)
        assert runtime_after is not None
        assert fw not in runtime_after.connections
    finally:
        if not task.done():
            task.cancel()


# ---------------- _handle_text_message: ask / ask_manual 单测 ----------------


class FakeManager(SessionManager):
    """SessionManager 子类，broadcast / append_question 记录调用。"""

    def __init__(self) -> None:
        super().__init__()
        self.broadcasts: list[tuple[int, dict]] = []
        self.appended_questions: list[tuple[int, int, str, float]] = []
        self.stop_calls: list[tuple[int, str]] = []
        self.answer_chunks: list[tuple[int, int, str, str]] = []
        self.finalized: list[int] = []

    async def broadcast(self, session_id: int, msg: dict) -> None:
        self.broadcasts.append((session_id, msg))

    async def append_question(
        self, session_id: int, qa_id: int, text: str, asked_at: float
    ) -> None:
        self.appended_questions.append((session_id, qa_id, text, asked_at))

    async def stop(self, session_id: int, reason: str) -> None:
        self.stop_calls.append((session_id, reason))

    async def update_answer_chunk(
        self, session_id: int, qa_id: int, segment: str, text: str
    ) -> None:
        self.answer_chunks.append((session_id, qa_id, segment, text))

    async def finalize_answer(self, session_id: int) -> None:
        self.finalized.append(session_id)


async def test_handle_ask_unknown_qa_id_emits_error(
    patch_session_local, make_user, make_session
):
    user = make_user()
    sess = make_session(user.id)
    fake_mgr = FakeManager()
    fw = FakeWS()

    stop = await ws_module._handle_text_message(
        manager=fake_mgr,
        websocket=fw,
        session_id=sess.id,
        text=json.dumps({"type": "ask", "qa_id": 99999}),
    )
    assert stop is False
    msgs = fw.sent_messages()
    assert any(
        m.get("type") == "error" and m.get("code") == "QA_NOT_FOUND"
        for m in msgs
    )


async def test_handle_ask_manual_inserts_qa_and_broadcasts(
    patch_session_local, monkeypatch, make_user, make_session, db_session
):
    """ask_manual：建一行 SessionQA(source='manual') + broadcast question_added + 起 LLM task。"""
    user = make_user()
    sess = make_session(user.id)
    fake_mgr = FakeManager()
    fw = FakeWS()

    # 把 _run_ask 替换成 sentinel，避免真跑 LLM
    ran: list[tuple[int, int, str]] = []

    async def fake_run_ask(mgr, session_id, qa_id, question):
        ran.append((session_id, qa_id, question))

    monkeypatch.setattr(ws_module, "_run_ask", fake_run_ask)

    stop = await ws_module._handle_text_message(
        manager=fake_mgr,
        websocket=fw,
        session_id=sess.id,
        text=json.dumps({"type": "ask_manual", "text": "为什么离职"}),
    )
    assert stop is False

    # DB 多了一行
    qas = (
        db_session.query(SessionQA)
        .filter(SessionQA.session_id == sess.id)
        .all()
    )
    assert len(qas) == 1
    assert qas[0].source == "manual"
    assert qas[0].question == "为什么离职"

    # broadcast question_added
    assert len(fake_mgr.broadcasts) == 1
    sid, msg = fake_mgr.broadcasts[0]
    assert sid == sess.id
    assert msg["type"] == "question_added"
    assert msg["text"] == "为什么离职"

    # _run_ask task 起来了——给 event loop 一次机会跑
    await asyncio.sleep(0)
    assert len(ran) == 1
    assert ran[0][1] == qas[0].id
    assert ran[0][2] == "为什么离职"


async def test_handle_ask_manual_empty_emits_error(
    patch_session_local, make_user, make_session
):
    user = make_user()
    sess = make_session(user.id)
    fake_mgr = FakeManager()
    fw = FakeWS()

    stop = await ws_module._handle_text_message(
        manager=fake_mgr,
        websocket=fw,
        session_id=sess.id,
        text=json.dumps({"type": "ask_manual", "text": "   "}),
    )
    assert stop is False
    msgs = fw.sent_messages()
    assert any(
        m.get("type") == "error" and m.get("code") == "EMPTY_QUESTION"
        for m in msgs
    )


# ---------------- _run_ask 单测 ----------------


class FakeLLMService:
    """Mock LLMService。stream_three_segments 按预定义事件 yield。"""

    last_cfg: Any = None

    def __init__(self, cfg: dict) -> None:
        FakeLLMService.last_cfg = cfg

    async def stream_three_segments(self, question: str):
        from app.llm.service import LLMEvent

        for seg in ("key_points", "script", "full"):
            yield LLMEvent(name=seg, type="start")
            yield LLMEvent(name=seg, type="chunk", text=f"[{seg}]chunk1")
            yield LLMEvent(name=seg, type="chunk", text=f"[{seg}]chunk2")
            yield LLMEvent(name=seg, type="end")


async def test_run_ask_streams_and_writes_back(
    patch_session_local, monkeypatch, make_user, make_session, db_session
):
    user = make_user()
    sess = make_session(user.id)
    qa = SessionQA(session_id=sess.id, question="解释 B+树", source="manual")
    db_session.add(qa)
    db_session.commit()
    db_session.refresh(qa)

    fake_mgr = FakeManager()

    monkeypatch.setattr(ws_module, "LLMService", FakeLLMService)
    # 让 cfg 看起来 "已配置"
    from app import configs as configs_module

    monkeypatch.setitem(
        configs_module._cache,
        "llm",
        {"providers": [{"name": "deepseek"}], "default": "deepseek"},
    )

    await ws_module._run_ask(fake_mgr, sess.id, qa.id, qa.question)

    # 三段都发了 start/chunk/chunk/end
    types_per_seg: dict[str, list[str]] = {}
    for sid, m in fake_mgr.broadcasts:
        if "segment" not in m:
            continue
        types_per_seg.setdefault(m["segment"], []).append(m["type"])
    for seg in ("key_points", "script", "full"):
        assert types_per_seg.get(seg) == [
            "answer_start",
            "answer_chunk",
            "answer_chunk",
            "answer_end",
        ]
    # finalize_answer 被调
    assert fake_mgr.finalized == [sess.id]

    # DB 回填
    db_session.expire_all()
    qa_after = db_session.query(SessionQA).filter_by(id=qa.id).one()
    assert qa_after.answer_key_points == "[key_points]chunk1[key_points]chunk2"
    assert qa_after.answer_script == "[script]chunk1[script]chunk2"
    assert qa_after.answer_full == "[full]chunk1[full]chunk2"
    assert qa_after.finished_at is not None


async def test_run_ask_no_llm_config_emits_error(
    patch_session_local, monkeypatch, make_user, make_session, db_session
):
    user = make_user()
    sess = make_session(user.id)
    qa = SessionQA(session_id=sess.id, question="x", source="manual")
    db_session.add(qa)
    db_session.commit()
    db_session.refresh(qa)

    fake_mgr = FakeManager()
    from app import configs as configs_module

    # cache 里没 llm，或没 providers
    configs_module._cache.pop("llm", None)

    await ws_module._run_ask(fake_mgr, sess.id, qa.id, qa.question)

    assert any(
        m.get("type") == "answer_error" and m.get("error") == "LLM not configured"
        for _, m in fake_mgr.broadcasts
    )


# ---------------- _asr_forward 单测 ----------------


class FakeASRWithEvents:
    """提供可控 stream_results 的 ASR fake。"""

    def __init__(self, events: list) -> None:
        self._events = events

    async def stream_results(self):
        for ev in self._events:
            yield ev


async def test_asr_forward_partial_and_final_broadcast(
    patch_session_local, make_user, make_session, db_session
):
    from app.asr.volcengine import ASREvent

    user = make_user()
    sess = make_session(user.id)
    fake_mgr = FakeManager()
    asr = FakeASRWithEvents(
        [
            ASREvent(type="partial", text="你好世", ts=1.0),
            ASREvent(type="final", text="什么是 B+ 树", ts=2.0),
            ASREvent(
                type="error", text="接口超时", ts=3.0
            ),
        ]
    )

    await ws_module._asr_forward(fake_mgr, sess.id, asr)

    types = [m["type"] for _, m in fake_mgr.broadcasts]
    # 预期 transcript_partial / transcript_final / question_added(final 命中) / error
    assert "transcript_partial" in types
    assert "transcript_final" in types
    # final "什么是 B+ 树" 含 "什么"，QuestionDetector 命中
    assert any(
        m.get("type") == "question_added" for _, m in fake_mgr.broadcasts
    )
    assert any(
        m.get("type") == "error" and m.get("code") == "ASR_ERROR"
        for _, m in fake_mgr.broadcasts
    )

    # 命中后 DB 应有 detected qa
    rows = (
        db_session.query(SessionQA)
        .filter(SessionQA.session_id == sess.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].source == "detected"
