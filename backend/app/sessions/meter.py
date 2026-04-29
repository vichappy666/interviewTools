"""扣费心跳 meter（M2 T9）。

设计：

- **user-level task**：每个 user 在 active session 期间起 *一个* 后台 task，每秒
  按当前 active session 数 N 扣 N 秒。多 session 并发时不会重复扣。
- **幂等启动**：``ensure_running(user_id)`` 在每次 session start / ws accept 时调，
  如果该 user 已有 task 在跑就 noop。
- **自然退出**：task 内部检测到该 user 0 个 active session 时自己 return；外部也可
  ``stop_for_user`` 强制 cancel 兜底。
- **余额耗尽**：``grant`` 抛 INSUFFICIENT_BALANCE 时调
  ``manager.stop_all_for_user(user_id, reason='balance_zero')`` + 退出。
- **心跳广播**：跨 10 秒边界时推 ``balance_update``；余额 ≤60s 时每 5 秒推一次
  ``balance_low``。

模块级状态 ``_user_meter_tasks`` / ``_user_locks`` 在测试间会污染，测试用
``_reset_for_tests()`` 清理。
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from app.billing.ledger import grant
from app.db import SessionLocal
from app.models.session import Session as SessionModel


logger = logging.getLogger(__name__)


# ---------------- module state ----------------

_user_meter_tasks: dict[int, asyncio.Task] = {}
"""user_id → 该用户的 meter task。task done / 未注册即等于 'no meter running'。"""

_user_locks: dict[int, asyncio.Lock] = {}
"""user_id → 串行化扣费的锁（同 user 一秒内只一次扣）。"""

_locks_guard = asyncio.Lock()
"""保护 _user_locks dict 的增删（避免并发 ensure 时双建锁）。"""


# ---------------- public API ----------------


async def ensure_running(user_id: int) -> None:
    """启动该 user 的 meter task；如果已经在跑就 noop（幂等）。

    在 session start endpoint 或 ws accept 后调用。
    """
    task = _user_meter_tasks.get(user_id)
    if task is not None and not task.done():
        return
    _user_meter_tasks[user_id] = asyncio.create_task(
        _run_meter(user_id), name=f"meter-{user_id}"
    )


async def stop_for_user(user_id: int) -> None:
    """主动停止该 user 的 meter task（兜底；正常情况下 task 自己检测 0 active 退出）。

    幂等：没有 task 就 no-op。
    """
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


def _reset_for_tests() -> None:
    """测试 fixture 用：cancel 所有 task 并清空所有模块级状态。

    本函数不 await cancel —— 测试如果需要等 task 结束自行 await。
    """
    for t in _user_meter_tasks.values():
        if not t.done():
            t.cancel()
    _user_meter_tasks.clear()
    _user_locks.clear()


# ---------------- internal helpers ----------------


async def _get_user_lock(user_id: int) -> asyncio.Lock:
    """惰性建用户级 mutex。"""
    async with _locks_guard:
        lock = _user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _user_locks[user_id] = lock
        return lock


def _is_insufficient_balance(exc: HTTPException) -> bool:
    """检测 grant 抛的 HTTPException 是不是 INSUFFICIENT_BALANCE。"""
    detail = getattr(exc, "detail", None)
    if not isinstance(detail, dict):
        return False
    err = detail.get("error")
    if not isinstance(err, dict):
        return False
    return err.get("code") == "INSUFFICIENT_BALANCE"


# ---------------- meter task ----------------


async def _run_meter(user_id: int) -> None:
    """每秒扣一次 N 秒（N = 该 user 当前 active session 数）。

    - 0 active → return（不扣，自然结束）
    - INSUFFICIENT_BALANCE → 调 manager.stop_all_for_user 并 return
    - 其他异常 → log + return（避免无限 loop 抛错日志洪水）
    """
    # lazy import 避免循环依赖
    from app.sessions.manager import manager

    last_broadcast_floor = -1
    """上次 balance_update 广播时的 (balance // 10) 值；-1 让首轮一定推一次。"""
    tick = 0  # 累计 tick 数，用于 balance_low 节流

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
                        return  # user 已无 active session → 退出

                    ref_id = active_sessions[0].id
                    session_ids = [s.id for s in active_sessions]

                    try:
                        new_balance = grant(
                            db=db,
                            user_id=user_id,
                            delta_seconds=-n,
                            reason="session",
                            ref_type="session",
                            ref_id=ref_id,
                        )
                    except HTTPException as exc:
                        if _is_insufficient_balance(exc):
                            logger.info(
                                "user %d balance exhausted, stopping all sessions",
                                user_id,
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
                        logger.warning(
                            "grant raised non-balance HTTPException for user %d: %s",
                            user_id,
                            exc.detail,
                        )
                        return

                    # 广播 balance_update：跨 10 秒边界时推一次（首轮强制推）
                    cur_floor = new_balance // 10
                    if last_broadcast_floor < 0 or cur_floor != last_broadcast_floor:
                        last_broadcast_floor = cur_floor
                        for sid in session_ids:
                            await manager.broadcast(
                                sid,
                                {
                                    "type": "balance_update",
                                    "balance_seconds": new_balance,
                                },
                            )

                    # balance_low：余额 ≤60s 时每 5 秒推一次
                    if 0 < new_balance <= 60 and tick % 5 == 0:
                        for sid in session_ids:
                            await manager.broadcast(
                                sid,
                                {
                                    "type": "balance_low",
                                    "balance_seconds": new_balance,
                                },
                            )
                finally:
                    db.close()
    except asyncio.CancelledError:
        return
    except Exception:  # noqa: BLE001
        logger.exception("meter task crashed for user %d", user_id)
        return
