"""Tests for sessions / session_qa ORM models (M2 T2)."""
from app.auth.security import hash_password
from app.models.session import Session as SessionModel
from app.models.session_qa import SessionQA
from app.models.user import User


def _make_user(db, username="alice", password="secret123"):
    u = User(username=username, password_hash=hash_password(password))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------------- sessions ----------------

def test_insert_active_session(db_session):
    u = _make_user(db_session)
    s = SessionModel(user_id=u.id)
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)

    fetched = db_session.query(SessionModel).filter_by(id=s.id).one()
    assert fetched.user_id == u.id
    assert fetched.status == "active"
    assert fetched.total_seconds == 0
    assert fetched.ended_at is None
    assert fetched.end_reason is None
    assert fetched.started_at is not None


def test_session_defaults(db_session):
    """新插入的 session：status='active', total_seconds=0, ended_at=None。"""
    u = _make_user(db_session)
    s = SessionModel(user_id=u.id)
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)

    assert s.status == "active"
    assert s.total_seconds == 0
    assert s.ended_at is None
    assert s.end_reason is None


def test_insert_session_qa_and_query_via_session_id(db_session):
    """插入 session 后再插入 session_qa，按 session_id 查询拿到 qa 列表。"""
    u = _make_user(db_session)
    s = SessionModel(user_id=u.id)
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)

    qa1 = SessionQA(
        session_id=s.id,
        question="什么是 Python 的 GIL？",
        source="detected",
    )
    qa2 = SessionQA(
        session_id=s.id,
        question="谈谈 MySQL 的事务隔离级别",
        answer_key_points="读未提交 / 读已提交 / 可重复读 / 串行化",
        answer_script="MySQL 默认 RR ...",
        answer_full="完整回答 ...",
        source="manual",
    )
    db_session.add_all([qa1, qa2])
    db_session.commit()

    qas = (
        db_session.query(SessionQA)
        .filter_by(session_id=s.id)
        .order_by(SessionQA.id)
        .all()
    )
    assert len(qas) == 2
    assert qas[0].question == "什么是 Python 的 GIL？"
    assert qas[0].source == "detected"
    assert qas[0].answer_key_points is None
    assert qas[0].finished_at is None
    assert qas[1].source == "manual"
    assert qas[1].answer_key_points == "读未提交 / 读已提交 / 可重复读 / 串行化"
    assert qas[1].answer_script == "MySQL 默认 RR ..."
    assert qas[1].answer_full == "完整回答 ..."


def test_session_end_fields_writable(db_session):
    """ended_at / end_reason / status 在结束时可被写入。"""
    from datetime import datetime

    u = _make_user(db_session)
    s = SessionModel(user_id=u.id)
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)

    s.status = "ended"
    s.end_reason = "user_stop"
    s.ended_at = datetime.utcnow()
    s.total_seconds = 123
    db_session.commit()
    db_session.refresh(s)

    assert s.status == "ended"
    assert s.end_reason == "user_stop"
    assert s.ended_at is not None
    assert s.total_seconds == 123


def test_session_qa_source_field_required(db_session):
    """source 字段 NOT NULL —— ENUM 类型签名存在。"""
    # SQLite 不会强制 ENUM 取值范围，但 nullable=False 在 SQLite 上仍生效。
    # 这里验证模型定义中 source 列存在，且是 Enum 类型（detected/manual）。
    from sqlalchemy import Enum as SAEnum

    col = SessionQA.__table__.c.source
    assert col.nullable is False
    assert isinstance(col.type, SAEnum)
    assert set(col.type.enums) == {"detected", "manual"}


def test_session_status_enum_definition(db_session):
    """sessions.status ENUM 定义为 ('active','ended')。"""
    from sqlalchemy import Enum as SAEnum

    col = SessionModel.__table__.c.status
    assert col.nullable is False
    assert isinstance(col.type, SAEnum)
    assert set(col.type.enums) == {"active", "ended"}


def test_session_end_reason_enum_definition(db_session):
    """sessions.end_reason ENUM 包含 5 个取值，可空。"""
    from sqlalchemy import Enum as SAEnum

    col = SessionModel.__table__.c.end_reason
    assert col.nullable is True
    assert isinstance(col.type, SAEnum)
    assert set(col.type.enums) == {
        "user_stop",
        "balance_zero",
        "idle_timeout",
        "admin_force",
        "error",
    }
