"""Configs key-value store with in-memory cache + 30s background refresh.

Usage:
    from app import configs
    rate = configs.get("recharge.rate_per_usdt", 60)
    configs.save(db, "session.max_concurrent", 10)  # immediate cache update
"""
import asyncio
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.config_kv import ConfigKV


logger = logging.getLogger(__name__)

_cache: dict[str, Any] = {}
_lock = asyncio.Lock()  # only used by the watcher; sync get/save don't need it
_watcher_task: Optional[asyncio.Task] = None


def get(key: str, default: Any = None) -> Any:
    """Synchronous read from in-memory cache."""
    return _cache.get(key, default)


def all_keys() -> dict[str, Any]:
    """Snapshot of full cache (used by admin GET endpoint)."""
    return dict(_cache)


def init_cache(db: Session) -> None:
    """Load all configs from DB into the cache (call on app startup)."""
    rows = db.query(ConfigKV).all()
    new_cache = {row.key: row.value for row in rows}
    _cache.clear()
    _cache.update(new_cache)
    logger.info("configs cache loaded with %d keys", len(_cache))


def save(db: Session, key: str, value: Any) -> ConfigKV:
    """Insert or update one config and refresh the cache atomically."""
    row = db.query(ConfigKV).filter(ConfigKV.key == key).one_or_none()
    if row is None:
        row = ConfigKV(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    db.refresh(row)
    _cache[key] = value
    return row


async def _refresh_loop(interval_seconds: int = 30) -> None:
    """Background task: re-pull configs from DB every N seconds.

    This catches out-of-band changes (e.g., another process / DBA edit).
    Errors during refresh are logged but don't stop the loop.
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            db = SessionLocal()
            try:
                rows = db.query(ConfigKV).all()
                fresh = {row.key: row.value for row in rows}
                async with _lock:
                    _cache.clear()
                    _cache.update(fresh)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("configs refresh failed; retrying next cycle")


def start_watcher(
    loop: asyncio.AbstractEventLoop, interval_seconds: int = 30
) -> asyncio.Task:
    """Start the background refresh loop.

    Returns the task so caller can cancel on shutdown.
    """
    global _watcher_task
    _watcher_task = loop.create_task(_refresh_loop(interval_seconds))
    return _watcher_task


async def stop_watcher() -> None:
    global _watcher_task
    if _watcher_task is not None:
        _watcher_task.cancel()
        try:
            await _watcher_task
        except asyncio.CancelledError:
            pass
        _watcher_task = None
