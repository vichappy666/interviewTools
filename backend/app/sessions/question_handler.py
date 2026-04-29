"""ASR final → question_detector → DB + broadcast 的小 helper（M2 T7）。

T8 在 ws.py 收到 ASR final 事件后会调用 :func:`handle_asr_final`：

1. 把 final 文本喂给会话级别的 :class:`QuestionDetector`；
2. 命中则插一行 ``session_qa(source='detected')``，并通过
   :class:`SessionManager` 更新 snapshot + broadcast ``question_added``；
3. 不命中静默返回 ``None``。

`session_qa` 留 ``answer_*`` / ``finished_at`` 为 NULL，等用户在 UI
点击该问题主动触发 LLM 时再回填（这是 T8/T?+ 的事，不在本 helper 里做）。

这里**只放一个函数**，刻意不做成 class——detector 实例由调用方持有，
db / manager 都是参数注入，方便测试 mock。
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.models.session_qa import SessionQA
from app.question_detector import QuestionDetector
from app.sessions.manager import SessionManager


async def handle_asr_final(
    db: DBSession,
    manager: SessionManager,
    session_id: int,
    text: str,
    ts: float,
    detector: QuestionDetector,
) -> int | None:
    """喂一条 ASR final 文本，命中问题则落库 + 广播。

    Args:
        db: 当前请求的 SQLAlchemy session（调用方自管生命周期）。
        manager: :class:`SessionManager` 实例（生产用 module-level 单例，
            测试可注入 mock）。
        session_id: 当前会话 id（须已注册到 manager 且对应 ``sessions`` 表行存在）。
        text: ASR finalize 出的整句文本。
        ts: ASR 事件时间戳（秒，浮点），落到 broadcast 的 ``asked_at`` 字段。
        detector: 会话级 :class:`QuestionDetector` 实例（每个 session 一个，
            由调用方持有）。

    Returns:
        若命中则返回新插入的 ``session_qa.id``；不命中返回 ``None``。
    """
    hit = detector.feed(text)
    if hit is None:
        return None

    qa = SessionQA(session_id=session_id, question=hit, source="detected")
    db.add(qa)
    db.commit()
    db.refresh(qa)

    await manager.append_question(session_id, qa.id, hit, ts)
    await manager.broadcast(
        session_id,
        {
            "type": "question_added",
            "qa_id": qa.id,
            "text": hit,
            "asked_at": ts,
        },
    )
    return qa.id
