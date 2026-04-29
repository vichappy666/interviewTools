"""SessionManager: in-memory 运行时容器（M2 T4）。

进程内单例，持有所有 active session 的运行时状态：

- 已 join 的 WebSocket 连接集合
- ASR 客户端（T5 才会真正塞进来；T4 阶段都是 None）
- 计费心跳任务（T9 才会真正塞进来；T4 阶段都是 None）
- 状态快照（partial / finals / questions / current_answer）

⚠️ 注意：plan 文档里写的是 ``app/session/manager.py``（单数），但 T3 已经
建了 ``app/sessions/`` 复数包以避开 SQLAlchemy ``Session`` 类名冲突，
所以本文件落在 ``app/sessions/manager.py`` 下。

M2 单进程单实例够用；M3+ 多 worker 上线后再考虑用 Redis pub/sub 替换 broadcast。
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------- StateSnapshot ----------------


@dataclass
class StateSnapshot:
    """会话内存态快照。后加入的设备 join 后由 ws handler 推送整份给客户端。"""

    transcript_finals: list[dict] = field(default_factory=list)
    """已 finalize 的 ASR 段落，每条 ``{"text": str, "ts": float}``。"""

    transcript_partial: str = ""
    """最新未 finalize 的 partial 文本（覆盖式更新）。"""

    questions: list[dict] = field(default_factory=list)
    """检测到的面试问题列表，每条 ``{"qa_id": int, "text": str, "asked_at": float}``。"""

    current_answer: Optional[dict] = None
    """当前 LLM 回答 ``{"qa_id": int, "sections": {"key_points": {"text": str, "state": "streaming"|"done"}, ...}}``。"""


# ---------------- SessionRuntime ----------------


@dataclass
class SessionRuntime:
    """单个 session 的运行时状态。"""

    id: int
    user_id: int
    started_at: datetime
    connections: set[Any] = field(default_factory=set)
    """已 join 的 WebSocket 连接（fastapi.WebSocket，留 Any 以便 mock 测试）。"""
    asr_client: Optional[Any] = None
    """T5 才接入；T4 阶段保持 None。"""
    asr_forward_task: Optional[asyncio.Task] = None
    """T8 接入：把 asr_client.stream_results() 的事件转 broadcast 的会话级 task。"""
    meter_task: Optional[asyncio.Task] = None
    """T9 才接入；T4 阶段保持 None。"""
    state_snapshot: StateSnapshot = field(default_factory=StateSnapshot)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """更改 state_snapshot 时持有，防并发写竞态。"""


# ---------------- SessionManager ----------------


class SessionManager:
    """进程内单例，集中管理所有 active session 的运行时态。

    设计原则：
    - 简单：用 module-level 实例，避免元类 / threading.Lock / 注册式 singleton
    - 异步：所有可能并发的操作都用 asyncio.Lock 保护
    - 容错：broadcast 单条 ws 失败不影响其他 ws；stop 幂等
    """

    def __init__(self) -> None:
        self.sessions: dict[int, SessionRuntime] = {}
        self._lock = asyncio.Lock()
        """保护 ``self.sessions`` dict 本身的增删（不保护单 runtime 的 snapshot）。"""

    # ---------- 生命周期 ----------

    async def register_session(
        self,
        session_id: int,
        user_id: int,
        started_at: datetime,
    ) -> SessionRuntime:
        """注册一个新的 session runtime。已存在则直接返回原有 runtime（幂等）。"""
        async with self._lock:
            existing = self.sessions.get(session_id)
            if existing is not None:
                return existing
            runtime = SessionRuntime(
                id=session_id,
                user_id=user_id,
                started_at=started_at,
            )
            self.sessions[session_id] = runtime
            return runtime

    def get(self, session_id: int) -> SessionRuntime | None:
        """同步 getter：拿不到返回 None。"""
        return self.sessions.get(session_id)

    def list_for_user(self, user_id: int) -> list[SessionRuntime]:
        """列出某用户当前所有 active runtime（同步）。"""
        return [r for r in self.sessions.values() if r.user_id == user_id]

    # ---------- 连接管理 ----------

    async def add_connection(self, session_id: int, ws: Any) -> SessionRuntime:
        """把一个 WebSocket 加入 session 的 connections 集合。

        Returns:
            当前 runtime（含 state_snapshot），调用方可据此把 snapshot 推回 ws。

        Raises:
            KeyError: session 未注册。
        """
        runtime = self.sessions.get(session_id)
        if runtime is None:
            raise KeyError(f"session {session_id} not registered")
        async with runtime._lock:
            runtime.connections.add(ws)
        return runtime

    async def remove_connection(self, session_id: int, ws: Any) -> int:
        """从 connections 中移除一个 ws，返回剩余连接数。session 不存在返回 0。"""
        runtime = self.sessions.get(session_id)
        if runtime is None:
            return 0
        async with runtime._lock:
            runtime.connections.discard(ws)
            return len(runtime.connections)

    async def broadcast(self, session_id: int, msg: dict) -> None:
        """JSON-encode msg 并群发到 session 的所有 ws。

        - 单个 ws send 失败仅 log warning，不抛、不删（让 disconnect handler 清理，避免双重删除）
        - 遍历前先 ``list(connections)`` 复制一份，避免迭代中被修改
        - 不持锁：snapshot 已经写好，发送阶段允许并发
        """
        runtime = self.sessions.get(session_id)
        if runtime is None:
            logger.debug("broadcast to missing session %d skipped", session_id)
            return
        payload = json.dumps(msg, ensure_ascii=False)
        for ws in list(runtime.connections):
            try:
                await ws.send_text(payload)
            except Exception as exc:  # noqa: BLE001 — broadcast 必须吞所有错
                logger.warning(
                    "broadcast to ws on session %d failed: %s", session_id, exc
                )

    async def stop(self, session_id: int, reason: str) -> None:
        """关闭一个 session：取消 meter、关 asr、广播 ended、断开所有 ws、从 dict 删除。

        幂等：session 不存在直接返回。
        """
        runtime = self.sessions.get(session_id)
        if runtime is None:
            return

        # 1. 取消计费心跳任务
        if runtime.meter_task is not None and not runtime.meter_task.done():
            runtime.meter_task.cancel()

        # 1b. 取消 ASR forward task（T8）
        if (
            runtime.asr_forward_task is not None
            and not runtime.asr_forward_task.done()
        ):
            runtime.asr_forward_task.cancel()

        # 2. 关 asr 客户端（T5 之前都是 None；包 try/except 防 close 抛错）
        if runtime.asr_client is not None:
            try:
                await runtime.asr_client.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "asr_client.close on session %d raised: %s", session_id, exc
                )

        # 3. 广播 session_ended（在断开前发出去，让客户端先收到再被关）
        await self.broadcast(
            session_id,
            {"type": "session_ended", "reason": reason},
        )

        # 4. 关闭所有 ws；单条失败不影响其他
        for ws in list(runtime.connections):
            try:
                await ws.close(code=1000)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ws.close on session %d raised: %s", session_id, exc
                )
        runtime.connections.clear()

        # 5. 从注册表删除（持 _lock，避免和 register/list 竞态）
        async with self._lock:
            self.sessions.pop(session_id, None)

    async def stop_all_for_user(self, user_id: int, reason: str) -> int:
        """停掉某用户的所有 session（T9 余额=0 时调用），返回停了几个。"""
        targets = [r.id for r in self.list_for_user(user_id)]
        for sid in targets:
            await self.stop(sid, reason)
        return len(targets)

    # ---------- State snapshot 更新 ----------
    # 这些方法供 WS handler / ASR / LLM 写回内存态，每个内部持 runtime._lock 防竞态。

    async def update_partial(self, session_id: int, text: str) -> None:
        """覆盖式更新当前 partial 文本。session 不存在静默忽略。"""
        runtime = self.sessions.get(session_id)
        if runtime is None:
            return
        async with runtime._lock:
            runtime.state_snapshot.transcript_partial = text

    async def append_final(
        self, session_id: int, text: str, ts: float
    ) -> None:
        """append 一条 finalize 后的 ASR 段落，并清空当前 partial。"""
        runtime = self.sessions.get(session_id)
        if runtime is None:
            return
        async with runtime._lock:
            runtime.state_snapshot.transcript_finals.append(
                {"text": text, "ts": ts}
            )
            # finalize 之后 partial 清空（下一段 partial 会覆盖回来）
            runtime.state_snapshot.transcript_partial = ""

    async def append_question(
        self,
        session_id: int,
        qa_id: int,
        text: str,
        asked_at: float,
    ) -> None:
        """记录一个新检测到的问题。"""
        runtime = self.sessions.get(session_id)
        if runtime is None:
            return
        async with runtime._lock:
            runtime.state_snapshot.questions.append(
                {"qa_id": qa_id, "text": text, "asked_at": asked_at}
            )

    async def update_answer_chunk(
        self,
        session_id: int,
        qa_id: int,
        segment: str,
        text: str,
    ) -> None:
        """append 一段 LLM 流式 chunk 到 current_answer。

        Args:
            segment: ``"key_points"`` / ``"script"`` / ``"full"`` 之一。
            text: 这一 chunk 的增量文本。

        如果 ``current_answer`` 为 None 或 qa_id 不一致，会重置成新的一轮回答。
        """
        if segment not in ("key_points", "script", "full"):
            raise ValueError(f"invalid answer segment: {segment!r}")
        runtime = self.sessions.get(session_id)
        if runtime is None:
            return
        async with runtime._lock:
            ans = runtime.state_snapshot.current_answer
            if ans is None or ans.get("qa_id") != qa_id:
                ans = {"qa_id": qa_id, "sections": {}}
                runtime.state_snapshot.current_answer = ans
            sections = ans.setdefault("sections", {})
            seg = sections.setdefault(segment, {"text": "", "state": "streaming"})
            seg["text"] = seg.get("text", "") + text
            seg["state"] = "streaming"

    async def mark_answer_segment_done(
        self,
        session_id: int,
        qa_id: int,
        segment: str,
    ) -> None:
        """某一段流式结束，标 state='done'（snapshot 用）。"""
        if segment not in ("key_points", "script", "full"):
            raise ValueError(f"invalid answer segment: {segment!r}")
        runtime = self.sessions.get(session_id)
        if runtime is None:
            return
        async with runtime._lock:
            ans = runtime.state_snapshot.current_answer
            if ans is None or ans.get("qa_id") != qa_id:
                return
            sections = ans.setdefault("sections", {})
            seg = sections.setdefault(segment, {"text": "", "state": "done"})
            seg["state"] = "done"

    async def finalize_answer(self, session_id: int) -> None:
        """一轮 QA 回答完成，把 current_answer 清回 None。"""
        runtime = self.sessions.get(session_id)
        if runtime is None:
            return
        async with runtime._lock:
            runtime.state_snapshot.current_answer = None


# ---------------- Module-level singleton ----------------

manager = SessionManager()
"""进程级单例。调用方：``from app.sessions.manager import manager``。"""
