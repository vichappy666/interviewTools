"""Tests for VolcengineASRClient (async ASR interface).

策略：不连真火山服务。两类测试：
1. 直接对内部 _events queue + 业务方法（_segment / _emit_finals_dedup）做单元测试，
   走通 stream_results / close 的公共路径。
2. mock websockets.connect，构造合法火山协议帧，验证 _session 解析路径
   能产出 partial / final 事件。
"""
import asyncio
import gzip
import struct

import orjson
import pytest

from app.asr.volcengine import ASREvent, VolcengineASRClient


# ---------- 工具：构造火山 ASR 协议响应帧 ----------

def _make_server_frame(
    payload: dict,
    *,
    sequence: int = 1,
    is_last: bool = False,
) -> bytes:
    """构造一个合法的 FULL_SERVER_RESPONSE 协议帧（带 sequence + JSON + GZIP）。

    header 字节布局（火山 ASR V3）：
      byte0: protocol_version(4)=1 << 4 | header_size(4)=1            -> 0x11
      byte1: message_type(4)=FULL_SERVER_RESPONSE(9) << 4 | flags(4)  -> 0x90 | flags
      byte2: serial(4)=JSON(1) << 4 | compression(4)=GZIP(1)          -> 0x11
      byte3: reserved                                                  -> 0x00
    flags: bit0 = POS_SEQUENCE(有序号), bit1 = is_last_package
    """
    flags = 0x01  # POS_SEQUENCE
    if is_last:
        flags |= 0x02
    header = bytes([0x11, (9 << 4) | flags, 0x11, 0x00])

    seq_bytes = struct.pack(">i", sequence)
    msg_bytes = gzip.compress(orjson.dumps(payload))
    size_bytes = struct.pack(">I", len(msg_bytes))
    return header + seq_bytes + size_bytes + msg_bytes


# ---------- mock WebSocket（async context manager）----------

class FakeWS:
    """假 WebSocket：recv 按预定义脚本返回；send 收下不做事。"""

    def __init__(self, recv_script: list[bytes]):
        # script[0] 通常是握手响应；其余是后续 server push
        self._script = list(recv_script)
        self.sent: list[bytes] = []
        self._closed = False

    async def send(self, data) -> None:
        self.sent.append(bytes(data))

    async def recv(self):
        if self._closed:
            raise ConnectionError("closed")
        if not self._script:
            # 脚本耗尽 → 模拟挂起，让 _recv_loop 命中 1s timeout
            await asyncio.sleep(10)
            raise ConnectionError("script exhausted")
        return self._script.pop(0)

    async def close(self) -> None:
        self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._closed = True
        return False


# ---------- 测试 ----------

@pytest.mark.asyncio
async def test_create_start_close_no_raise(monkeypatch):
    """创建 + start + close 不抛。close() 后 main_task 已清空。"""
    fake_ws = FakeWS([
        # 握手响应：code=0 隐式（无 code 字段即视为成功）
        _make_server_frame({}, sequence=1),
    ])

    def fake_connect(*args, **kwargs):
        return fake_ws

    monkeypatch.setattr("websockets.connect", fake_connect)

    client = VolcengineASRClient({"app_key": "k", "access_key": "a"})
    await client.start()
    # 给 _connect_loop 一点时间跑握手
    await asyncio.sleep(0.05)
    await client.close()

    assert client._main_task is None
    assert client._closed is True


@pytest.mark.asyncio
async def test_close_idempotent(monkeypatch):
    """close() 调两次不抛，状态稳定。"""
    fake_ws = FakeWS([_make_server_frame({}, sequence=1)])
    monkeypatch.setattr("websockets.connect", lambda *a, **k: fake_ws)

    client = VolcengineASRClient({"app_key": "k", "access_key": "a"})
    await client.start()
    await asyncio.sleep(0.05)
    await client.close()
    await client.close()  # 第二次：不应抛
    assert client._closed is True


@pytest.mark.asyncio
async def test_feed_pcm_before_start_silently_drops():
    """没 start 时 feed_pcm 不抛（silently drop）—— 这是契约。"""
    client = VolcengineASRClient({"app_key": "k", "access_key": "a"})
    # 未 start，未连接
    await client.feed_pcm(b"\x00" * 3200)  # 不抛即合格


@pytest.mark.asyncio
async def test_stream_results_yields_events_from_queue():
    """直接往 _events queue 塞事件，验证 stream_results 能拉到。

    这是 fallback 测试路径：绕开真实 _session，验证 queue → async iterator
    的契约成立。"""
    client = VolcengineASRClient({"app_key": "k", "access_key": "a"})

    await client._events.put(ASREvent(type="partial", text="你好", ts=1.0))
    await client._events.put(ASREvent(type="final", text="你好世界。", ts=2.0))

    collected = []

    async def consume():
        async for ev in client.stream_results():
            collected.append(ev)
            if len(collected) >= 2:
                break

    await asyncio.wait_for(consume(), timeout=2.0)
    assert collected[0].type == "partial"
    assert collected[0].text == "你好"
    assert collected[1].type == "final"
    assert collected[1].text == "你好世界。"

    await client.close()


@pytest.mark.asyncio
async def test_error_event_in_queue():
    """_emit_error 把错误事件正确推入 queue，stream_results 能拿到。"""
    client = VolcengineASRClient({"app_key": "k", "access_key": "a"})

    await client._emit_error("boom")

    async def first():
        async for ev in client.stream_results():
            return ev

    ev = await asyncio.wait_for(first(), timeout=1.0)
    assert ev.type == "error"
    assert ev.text == "boom"
    await client.close()


@pytest.mark.asyncio
async def test_session_parses_partial_and_final(monkeypatch):
    """完整路径：mock ws 推一帧 partial + 一帧 final（带句末标点）。

    验证 _session → _recv_loop → _segment → final/partial 事件落 queue。
    """
    handshake = _make_server_frame({}, sequence=1)
    # 第一条：partial 文本（无句末标点）→ 应该出 partial
    partial_frame = _make_server_frame(
        {"result": {"text": "你好"}}, sequence=2
    )
    # 第二条：含句末标点 → 应该出 final（句子去重首发）
    final_frame = _make_server_frame(
        {"result": {"text": "你好，世界。"}}, sequence=3
    )

    fake_ws = FakeWS([handshake, partial_frame, final_frame])
    monkeypatch.setattr("websockets.connect", lambda *a, **k: fake_ws)

    client = VolcengineASRClient({"app_key": "k", "access_key": "a"})
    await client.start()

    collected = []

    async def consume():
        async for ev in client.stream_results():
            collected.append(ev)
            # 至少拿到一个 final 才停
            if any(e.type == "final" for e in collected):
                break

    try:
        await asyncio.wait_for(consume(), timeout=3.0)
    finally:
        await client.close()

    types = [e.type for e in collected]
    texts_by_type = {e.type: e.text for e in collected}
    assert "final" in types
    # final 文本应该是 "你好，世界。"（含句末标点的整句）
    assert "你好，世界。" in texts_by_type["final"]


@pytest.mark.asyncio
async def test_feed_pcm_sends_audio_when_connected(monkeypatch):
    """连接建立后 feed_pcm 应该实际触发 ws.send（即写入了一帧音频请求）。"""
    handshake = _make_server_frame({}, sequence=1)
    fake_ws = FakeWS([handshake])
    monkeypatch.setattr("websockets.connect", lambda *a, **k: fake_ws)

    client = VolcengineASRClient({"app_key": "k", "access_key": "a"})
    await client.start()

    # 等连接握手完成
    for _ in range(20):
        if client._connected:
            break
        await asyncio.sleep(0.05)

    assert client._connected, "握手应在 1s 内完成"

    sent_before = len(fake_ws.sent)
    await client.feed_pcm(b"\x00" * 3200)
    sent_after = len(fake_ws.sent)
    assert sent_after == sent_before + 1, "feed_pcm 应触发一次 ws.send"

    await client.close()
