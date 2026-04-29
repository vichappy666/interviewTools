"""logging_config 单元测试。"""
from __future__ import annotations

import json
import logging

from app.logging_config import JSONLineFormatter, setup_logging


def test_json_formatter_basic_fields():
    fmt = JSONLineFormatter()
    record = logging.LogRecord(
        name="x.y",
        level=logging.INFO,
        pathname="/x.py",
        lineno=42,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    out = fmt.format(record)
    obj = json.loads(out)
    assert obj["level"] == "INFO"
    assert obj["logger"] == "x.y"
    assert obj["msg"] == "hello world"
    assert "ts" in obj


def test_json_formatter_includes_extra():
    fmt = JSONLineFormatter()
    record = logging.LogRecord(
        name="x", level=logging.WARNING,
        pathname="/x.py", lineno=1, msg="oops", args=None, exc_info=None,
    )
    record.user_id = 42  # extra={'user_id': 42}
    record.action = "login"
    out = fmt.format(record)
    obj = json.loads(out)
    assert obj["user_id"] == 42
    assert obj["action"] == "login"


def test_json_formatter_handles_unjsonable_extra():
    """非 JSON 可序列化值降级为 repr，不抛异常。"""
    fmt = JSONLineFormatter()
    record = logging.LogRecord(
        name="x", level=logging.INFO,
        pathname="/x.py", lineno=1, msg="m", args=None, exc_info=None,
    )

    class Weird:
        def __repr__(self):
            return "<Weird()>"

    record.weird = Weird()
    out = fmt.format(record)
    obj = json.loads(out)
    assert obj["weird"] == "<Weird()>"


def test_setup_logging_idempotent_and_levels(monkeypatch):
    """多次调用不重复装 handler。"""
    setup_logging()
    n1 = len(logging.getLogger().handlers)
    setup_logging()
    n2 = len(logging.getLogger().handlers)
    assert n1 == n2 == 1


def test_health_db_endpoint_ok(client):
    """/api/health/db 在测试 in-memory SQLite 下应返回 200。"""
    r = client.get("/api/health/db")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_health_endpoint_returns_env(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "env" in body
