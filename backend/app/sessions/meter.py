"""扣费心跳 meter（M2 T9，重构版：会话结束时一次性写 ledger）。

设计：

- **用户级 task**：每个 user 在 active session 期间起 *一个* 后台 task，每秒
  累加该 user 所有 active session 的 elapsed 秒数（in-memory），不写 DB。
- **余额检查**：每 tick 用 ``users.balance_seconds - sum(已 elapsed)`` 判断剩余；
  ≤ 0 → 调 ``manager.stop_all_for_user(user_id, reason='balance_zero')``。
- **会话结束扣费**：``flush_session_charge(session_id, user_id)`` 在 session
  stop（用户主动 / 余额耗尽 / admin 强停）时调，把累计 elapsed 写一条
  ``balance_ledger`` 行 + 更新 ``users.balance_seconds``。
- **心跳广播**：跨 10 秒边界推 ``balance_update``；余额 ≤60s 每 5 秒推 ``balance_low``。
- **幂等启动**：``ensure_running(user_id)`` 重复调用 noop。

模块级状态在测试间会污染，测试用 ``_reset_for_tests()`` 清理。
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from app.billing.ledger import grant
from app.db import SessionLocal
from app.models.session import Session as SessionModel
from app.models.user import User


logger = logging.getLogger(__name__)


# ---------------- module state ----------------

_user_meter_tasks: dict[int, asyncio.Task] = {}
"""user_id → 该用户的 meter task。"""

_session_elapsed: dict[int, int] = {}
"""session_id → 已 elapsed 秒数（内存累计，结束时落地）。"""

_user_locks: dict[int, asyncio.Lock] = {}
"""user_id → 串行化每秒 tick 的锁。"""

_locks_guard = asyncio.Lock()


# ---------------- public API ----------------


async def ensure_running(user_id: int) -> None:
    """启动该 user 的 meter task；幂等。"""
    task = _user_meter_tasks.get(user_id)
    if task is not None and not task.done():
        return
    _user_meter_tasks[user_id] = asyncio.create_task(
        _run_meter(user_id), name=f"meter-{user_id}"
    )


async def stop_for_user(user_id: int) -> None:
    """主动 cancel 该 user 的 meter task；幂等。"""
    task = _user_meter_tasks.pop(user_id, None)
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:  # noqa: BLE001
        logger.debug("meter task for user %d raised on cancel", user_id)


def get_session_elapsed(session_id: int) -> int:
    """读当前 session 的 in-memory elapsed 秒数（未结算）。"""
    return _session_elapsed.get(session_id, 0)


async def flush_session_charge(session_id: int, user_id: int) -> int:
    """把 session 的累计 elapsed 一次性扣到 ledger，返回扣的秒数。

    幂等：第二次调返回 0。
    grant 失败（如余额已为 0）只 log，不抛 —— 防 user 主动 stop 时报 500。
    """
    elapsed = _session_elapsed.pop(session_id, 0)
    if elapsed <= 0:
        return 0
    db = SessionLocal()
    try:
        try:
            grant(
                db=db,
                user_id=user_id,
                delta_seconds=-elapsed,
                reason="session",
                ref_type="session",
                ref_id=session_id,
                note=f"session #{session_id} 累计 {elapsed}s",
            )
        except HTTPException as exc:
            logger.warning(
                "flush session %d charge=%ds for user %d failed: %s",
                session_id,
                elapsed,
                user_id,
                getattr(exc, "detail", exc),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "flush session %d charge=%ds crashed", session_id, elapsed
            )
    finally:
        db.close()
    return elapsed


def _reset_for_tests() -> None:
    """测试 fixture 用：cancel 所有 task 并清空所有模块级状态。"""
    for t in _user_meter_tasks.values():
        if not t.done():
            t.cancel()
    _user_meter_tasks.clear()
    _user_locks.clear()
    _session_elapsed.clear()


# ---------------- internal helpers ----------------


async def _get_user_lock(user_id: int) -> asyncio.Lock:
    async with _locks_guard:
        lock = _user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _user_locks[user_id] = lock
        return lock


# ---------------- meter task ----------------


async def _run_meter(user_id: int) -> None:
    """每秒：累加 elapsed → 检查余额 → 必要时 stop_all → 广播。"""
    from app.sessions.manager import manager  # lazy import 避免循环

    last_broadcast_floor = -1
    tick = 0

    try:
        while True:
            await asyncio.sleep(1.0)
            tick += 1

            lock = await _get_user_lock(user_id)
            async with lock:
                db = SessionLocal()
                try:
                    active_sessions = (
                        db.query(SessionModel)
                        .filter(
                            SessionModel.user_id == user_id,
                            SessionModel.status == "active",
                        )
                        .order_by(SessionModel.id.asc())
                        .all()
                    )
                    n = len(active_sessions)
                    if n == 0:
                        return

                    # 内存累加每个 active session 的 elapsed
                    for s in active_sessions:
                        _session_elapsed[s.id] = (
                            _session_elapsed.get(s.id, 0) + 1
                        )

                    user = (
                        db.query(User).filter(User.id == user_id).one_or_none()
                    )
                    if user is None:
                        logger.warning("user %d gone, stopping meter", user_id)
                        return

                    charged_so_far = sum(
                        _session_elapsed.get(s.id, 0) for s in active_sessions
                    )
                    remaining = (user.balance_seconds or 0) - charged_so_far
                    session_ids = [s.id for s in active_sessions]

                    if remaining <= 0:
                        logger.info(
                            "user %d balance exhausted (charged=%d, balance=%d), stopping all",
                            user_id,
                            charged_so_far,
                            user.balance_seconds or 0,
                        )
                        # flush 所有 active session 的累计扣费
                        for s in active_sessions:
                            try:
                                await flush_session_charge(s.id, user_id)
                            except Exception:  # noqa: BLE001
                                logger.exception(
                                    "flush_session_charge crashed sid=%d", s.id
                                )
                        try:
                            await manager.stop_all_for_user(
                                user_id, reason="balance_zero"
                            )
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "stop_all_for_user failed user=%d", user_id
                            )
                        return

                    # 广播 balance_update：跨 10 秒边界时推一次（首轮强制推）
                    cur_floor = remaining // 10
                    if last_broadcast_floor < 0 or cur_floor != last_broadcast_floor:
                        last_broadcast_floor = cur_floor
                        for sid in session_ids:
                            await manager.broadcast(
                                sid,
                                {
                                    "type": "balance_update",
                                    "balance_seconds": remaining,
                                },
                            )

                    # balance_low：余额 ≤60s 时每 5 秒推一次
                    if 0 < remaining <= 60 and tick % 5 == 0:
                        for sid in session_ids:
                            await manager.broadcast(
                                sid,
                                {
                                    "type": "balance_low",
                                    "balance_seconds": remaining,
                                },
                            )
                finally:
                    db.close()
    except asyncio.CancelledError:
        return
    except Exception:  # noqa: BLE001
        logger.exception("meter task crashed for user %d", user_id)
        return
