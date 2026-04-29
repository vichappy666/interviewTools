"""统一日志配置。

dev / local：人类可读单行格式
prod / ci：JSON-ish 单行（key=value），便于 journalctl + grep + 长期接入聚合

不引入新依赖，仅用标准库 logging。
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.config import settings


class JSONLineFormatter(logging.Formatter):
    """单行 JSON 输出（每条日志一行 JSON 对象）。"""

    _BASE_FIELDS = (
        "asctime", "levelname", "name", "message",
        "process", "thread", "pathname", "lineno",
    )

    def format(self, record: logging.LogRecord) -> str:
        # 让父类计算 asctime / message
        record.asctime = self.formatTime(record, self.datefmt)
        record.message = record.getMessage()

        out: dict[str, Any] = {
            "ts": record.asctime,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.message,
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        # 用户传 extra={...} 会写到 record 字典；过滤掉标准字段
        for k, v in record.__dict__.items():
            if k in out or k.startswith("_") or k in (
                "args", "msg", "levelno", "exc_info", "exc_text",
                "stack_info", "created", "msecs", "relativeCreated",
                "funcName", "filename", "module", "thread",
                "threadName", "processName", "process", "name",
                "levelname", "pathname", "lineno", "asctime",
                "message", "taskName",
            ):
                continue
            try:
                json.dumps(v)
                out[k] = v
            except (TypeError, ValueError):
                out[k] = repr(v)
        return json.dumps(out, ensure_ascii=False)


def setup_logging() -> None:
    """根据 settings.env 决定格式 + level。幂等，可多次调用。"""
    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if settings.env in ("prod", "ci"):
        handler.setFormatter(JSONLineFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # 第三方常见 logger 降噪
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
