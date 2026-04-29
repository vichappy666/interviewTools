"""/api/sessions/* REST endpoints (M2 T3).

注意：本模块的 SQLAlchemy ORM 模型 ``app.models.session.Session`` 类名与
``sqlalchemy.orm.Session`` 同名，本文件统一用 ``SessionModel`` 别名引用 ORM 类，
``Session`` 仍指 SQLAlchemy 的会话类。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import configs as configs_module
from app.deps import get_current_user, get_db
from app.models.session import Session as SessionModel
from app.models.user import User
from app.schemas.session import (
    SessionListResponse,
    SessionQARead,
    SessionRead,
    SessionStartResponse,
)
from app.sessions.manager import manager as session_manager
from app.sessions.meter import ensure_running as meter_ensure_running
from app.sessions.meter import flush_session_charge as meter_flush_session_charge
from app.sessions.meter import stop_for_user as meter_stop_for_user  # noqa: F401


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ---------------- POST /start ----------------

@router.post("/start", response_model=SessionStartResponse)
async def start_session(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionStartResponse:
    # 1. 校验余额 > 0
    if current.balance_seconds <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "INSUFFICIENT_BALANCE", "message": "余额不足"}},
        )

    # 2. 校验 active 数 < session.max_concurrent
    max_concurrent = int(configs_module.get("session.max_concurrent", 5))
    active_count = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == current.id, SessionModel.status == "active")
        .count()
    )
    if active_count >= max_concurrent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "SESSION_LIMIT",
                    "message": f"同时进行的会话数已达上限 {max_concurrent}",
                }
            },
        )

    # 3. INSERT
    s = SessionModel(user_id=current.id, status="active", total_seconds=0)
    db.add(s)
    db.commit()
    db.refresh(s)

    # 4. 启动扣费心跳 meter（M2 T9，幂等：该 user 已有 task 就 noop）
    await meter_ensure_running(current.id)

    return SessionStartResponse(session_id=s.id, ws_url=f"/ws/session/{s.id}")


# ---------------- POST /{id}/stop ----------------

@router.post("/{session_id}/stop", response_model=SessionRead)
async def stop_session(
    session_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionRead:
    s = db.query(SessionModel).filter(SessionModel.id == session_id).one_or_none()
    if s is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "SESSION_NOT_FOUND", "message": "会话不存在"}},
        )
    if s.user_id != current.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "无权操作该会话"}},
        )

    # 已 ended：幂等返回当前状态（仍然兜底通知一次内存 manager，防止脏 runtime 残留）
    if s.status == "ended":
        await session_manager.stop(session_id, reason="user_stop")
        return SessionRead.model_validate(s)

    # 1) 把累计 elapsed 一次性扣到 ledger（M2 改：每秒不写 ledger，结束时一笔）
    elapsed = await meter_flush_session_charge(session_id, current.id)

    # 2) 标 DB 行 ended
    s.status = "ended"
    s.ended_at = func.now()
    s.end_reason = "user_stop"
    s.total_seconds = elapsed
    db.commit()
    db.refresh(s)

    # 3) 通知 SessionManager 关闭 ws / asr / 内存 runtime
    await session_manager.stop(session_id, reason="user_stop")

    return SessionRead.model_validate(s)


# ---------------- GET /active ----------------

@router.get("/active", response_model=list[SessionRead])
def list_active(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SessionRead]:
    rows = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == current.id, SessionModel.status == "active")
        .order_by(SessionModel.started_at.desc(), SessionModel.id.desc())
        .all()
    )
    return [SessionRead.model_validate(r) for r in rows]


# ---------------- GET / (历史列表) ----------------

@router.get("/", response_model=SessionListResponse)
def list_history(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionListResponse:
    q = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == current.id)
        .order_by(SessionModel.started_at.desc(), SessionModel.id.desc())
    )
    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    return SessionListResponse(
        items=[SessionRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


# ---------------- GET /{id}/qa ----------------

@router.get("/{session_id}/qa", response_model=list[SessionQARead])
def list_qa(
    session_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SessionQARead]:
    s = db.query(SessionModel).filter(SessionModel.id == session_id).one_or_none()
    if s is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "SESSION_NOT_FOUND", "message": "会话不存在"}},
        )
    if s.user_id != current.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "无权操作该会话"}},
        )
    # M2 T3 暂返空数组；M4 实现真实 QA 列表查询
    return []
