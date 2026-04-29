"""Integration tests for :func:`app.sessions.question_handler.handle_asr_final` (M2 T7)。

用 conftest 的 in-memory SQLite + FakeManager（mock SessionManager 接口）。
覆盖：命中插库 + 广播 / 不命中跳过 / 多条混合 / 返回 qa_id / source / 广播 payload。
"""
from __future__ import annotations

import pytest

from app.auth.security import hash_password
from app.models.session import Session as SessionModel
from app.models.session_qa import SessionQA
from app.models.user import User
from app.question_detector import QuestionDetector
from app.sessions.question_handler import handle_asr_final


# ---------------- Fakes ----------------


class FakeManager:
    """记录 broadcast / append_question 调用，不关心 ws / runtime。"""

    def __init__(self) -> None:
        self.broadcasts: list[tuple[int, dict]] = []
        self.questions: list[tuple[int, int, str, float]] = []

    async def broadcast(self, session_id: int, msg: dict) -> None:
        self.broadcasts.append((session_id, msg))

    async def append_question(
        self,
        session_id: int,
        qa_id: int,
        text: str,
        asked_at: float,
    ) -> None:
        self.questions.append((session_id, qa_id, text, asked_at))


# ---------------- Fixtures ----------------


@pytest.fixture
def session_row(db_session) -> SessionModel:
    """创建一个 user + active session，让 session_qa 的 FK 满足。"""
    u = User(username="alice", password_hash=hash_password("secret123"))
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)

    s = SessionModel(user_id=u.id)
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


@pytest.fixture
def detector() -> QuestionDetector:
    return QuestionDetector()


@pytest.fixture
def fake_manager() -> FakeManager:
    return FakeManager()


# ---------------- Tests ----------------


async def test_hit_inserts_qa_and_broadcasts(
    db_session, session_row, detector, fake_manager
):
    """命中文本：DB 多一行 + broadcast / append_question 被调一次。"""
    qa_id = await handle_asr_final(
        db=db_session,
        manager=fake_manager,
        session_id=session_row.id,
        text="什么是 React 的 useEffect？",
        ts=12.5,
        detector=detector,
    )

    assert qa_id is not None
    qas = db_session.query(SessionQA).filter_by(session_id=session_row.id).all()
    assert len(qas) == 1
    assert qas[0].id == qa_id
    assert qas[0].question == "什么是 React 的 useEffect？"

    assert len(fake_manager.broadcasts) == 1
    assert len(fake_manager.questions) == 1
    sid, msg = fake_manager.broadcasts[0]
    assert sid == session_row.id
    assert msg["type"] == "question_added"


async def test_miss_returns_none_no_db_no_broadcast(
    db_session, session_row, detector, fake_manager
):
    """不命中：返回 None，DB 没新增，manager 没被调。"""
    qa_id = await handle_asr_final(
        db=db_session,
        manager=fake_manager,
        session_id=session_row.id,
        text="我今天去吃饭了",  # 无问号无特征词
        ts=3.0,
        detector=detector,
    )

    assert qa_id is None
    qas = db_session.query(SessionQA).filter_by(session_id=session_row.id).all()
    assert qas == []
    assert fake_manager.broadcasts == []
    assert fake_manager.questions == []


async def test_multiple_finals_only_questions_persist(
    db_session, session_row, detector, fake_manager
):
    """混合 5 条 final：DB 行数 = 命中数。"""
    finals = [
        ("好的我明白了", 1.0),                    # 太短 + 无特征词 → miss
        ("什么是 React 的 useEffect？", 2.0),     # 命中（问号 + 关键词）
        ("我今天去吃饭了", 3.0),                  # 普通陈述 → miss
        ("怎么实现快排", 4.0),                    # 命中（关键词）
        ("聊聊你的项目经历吧", 5.0),              # 命中（"聊聊"）
    ]
    hits: list[int] = []
    for text, ts in finals:
        qa_id = await handle_asr_final(
            db=db_session,
            manager=fake_manager,
            session_id=session_row.id,
            text=text,
            ts=ts,
            detector=detector,
        )
        if qa_id is not None:
            hits.append(qa_id)

    assert len(hits) == 3
    qas = (
        db_session.query(SessionQA)
        .filter_by(session_id=session_row.id)
        .order_by(SessionQA.id)
        .all()
    )
    assert len(qas) == 3
    assert [q.question for q in qas] == [
        "什么是 React 的 useEffect？",
        "怎么实现快排",
        "聊聊你的项目经历吧",
    ]
    assert len(fake_manager.broadcasts) == 3
    assert len(fake_manager.questions) == 3


async def test_qa_id_returned_matches_db(
    db_session, session_row, detector, fake_manager
):
    """返回的 qa_id 与 DB 中新插入行的 id 一致。"""
    qa_id = await handle_asr_final(
        db=db_session,
        manager=fake_manager,
        session_id=session_row.id,
        text="介绍一下你的项目",
        ts=7.0,
        detector=detector,
    )
    assert qa_id is not None
    row = db_session.query(SessionQA).filter_by(id=qa_id).one()
    assert row.id == qa_id
    assert row.session_id == session_row.id


async def test_source_is_detected(
    db_session, session_row, detector, fake_manager
):
    """命中插入的行 source == 'detected'，answer_* 都是 NULL。"""
    qa_id = await handle_asr_final(
        db=db_session,
        manager=fake_manager,
        session_id=session_row.id,
        text="为什么你想离职呢",
        ts=10.0,
        detector=detector,
    )
    assert qa_id is not None
    row = db_session.query(SessionQA).filter_by(id=qa_id).one()
    assert row.source == "detected"
    assert row.answer_key_points is None
    assert row.answer_script is None
    assert row.answer_full is None
    assert row.finished_at is None


async def test_broadcast_payload_shape(
    db_session, session_row, detector, fake_manager
):
    """broadcast msg 形状：type/qa_id/text/asked_at 四个字段。"""
    qa_id = await handle_asr_final(
        db=db_session,
        manager=fake_manager,
        session_id=session_row.id,
        text="谈谈你对微服务的理解",
        ts=42.5,
        detector=detector,
    )
    assert qa_id is not None
    assert len(fake_manager.broadcasts) == 1
    sid, msg = fake_manager.broadcasts[0]
    assert sid == session_row.id
    assert msg == {
        "type": "question_added",
        "qa_id": qa_id,
        "text": "谈谈你对微服务的理解",
        "asked_at": 42.5,
    }
    assert isinstance(msg["qa_id"], int)
    assert isinstance(msg["text"], str)
    assert isinstance(msg["asked_at"], float)

    # append_question 也用了同样的入参
    assert fake_manager.questions == [
        (session_row.id, qa_id, "谈谈你对微服务的理解", 42.5),
    ]
