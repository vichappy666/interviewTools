"""WebSocket endpoint ``/ws/session/{id}`` 完整实现（M2 T8）。

协议参考 plan 文档 spec 4.3 节。

握手流程：
1. JWT 解码 + type=='user' + session.user_id 校验 + status=='active' 校验
2. accept → register_session（如果 manager 里没有）→ add_connection
3. 立即推 snapshot
4. 如果是会话第一个连接，惰性启动 ASR client + ASR forward task

收到 binary 帧：转给 ``runtime.asr_client.feed_pcm``。
收到 text JSON：分发到 :func:`_handle_text_message`。

会话级资源（asr_client + asr_forward_task）由会话第一个连接惰性启动；
其他连接共享。session 结束时由 :meth:`SessionManager.stop` 统一清理。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

from fastapi import (
    APIRouter,
    Query,
    WebSocket,
    WebSocketDisconnect,
)

from app import configs as configs_module
from app.asr.volcengine import VolcengineASRClient
from app.auth.security import decode_token
from app.db import SessionLocal
from app.llm.service import LLMService
from app.models.session import Session as SessionModel
from app.models.session_qa import SessionQA
from app.question_detector import QuestionDetector
from app.sessions.manager import SessionManager, manager as default_manager
from app.sessions.question_handler import handle_asr_final


logger = logging.getLogger(__name__)

ws_router = APIRouter()


# ---------------- close codes ----------------
# WS 协议自定义 close code（4xxx 段，应用层使用）
CLOSE_AUTH = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_GONE = 4410


# ---------------- 主端点 ----------------


@ws_router.websocket("/ws/session/{session_id}")
async def session_ws(
    websocket: WebSocket,
    session_id: int,
    token: str = Query(...),
) -> None:
    """会话 WebSocket。鉴权 → register/add → snapshot → 收发循环。"""
    manager = _get_manager()

    # 1. JWT 解码
    payload = decode_token(token)
    if payload is None:
        await websocket.close(code=CLOSE_AUTH)
        return
    if payload.get("type") != "user":
        await websocket.close(code=CLOSE_FORBIDDEN)
        return
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        await websocket.close(code=CLOSE_AUTH)
        return

    # 2. 查 session
    db = SessionLocal()
    try:
        sess = (
            db.query(SessionModel)
            .filter(SessionModel.id == session_id)
            .one_or_none()
        )
        if sess is None:
            await websocket.close(code=CLOSE_NOT_FOUND)
            return
        if sess.user_id != user_id:
            await websocket.close(code=CLOSE_FORBIDDEN)
            return
        if sess.status != "active":
            await websocket.close(code=CLOSE_GONE)
            return
        started_at = sess.started_at or datetime.utcnow()
    finally:
        db.close()

    # 3. accept
    await websocket.accept()

    # 4. 注册到 manager（幂等）+ 加入连接集合
    await manager.register_session(
        session_id=session_id, user_id=user_id, started_at=started_at
    )
    runtime = await manager.add_connection(session_id, websocket)

    # 5. 推 snapshot
    snapshot = runtime.state_snapshot
    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "snapshot",
                    "transcript_finals": list(snapshot.transcript_finals),
                    "transcript_partial": snapshot.transcript_partial,
                    "questions": list(snapshot.questions),
                    "current_answer": snapshot.current_answer,
                },
                ensure_ascii=False,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws send snapshot failed: %s", exc)

    # 6. 启动会话级 ASR（仅会话第一个连接进来时启动）
    await _ensure_asr_started(manager, session_id, runtime)

    # 7. 主收发循环
    try:
        while True:
            msg = await websocket.receive()
            mtype = msg.get("type")
            if mtype == "websocket.disconnect":
                break

            data_bytes = msg.get("bytes")
            if data_bytes is not None:
                if runtime.asr_client is not None:
                    try:
                        await runtime.asr_client.feed_pcm(data_bytes)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("asr feed_pcm failed: %s", exc)
                continue

            data_text = msg.get("text")
            if data_text is not None:
                stop_loop = await _handle_text_message(
                    manager=manager,
                    websocket=websocket,
                    session_id=session_id,
                    text=data_text,
                )
                if stop_loop:
                    break
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("ws receive loop crashed for session %d", session_id)
    finally:
        # 注意：last connection 走了**不**自动停 session
        try:
            await manager.remove_connection(session_id, websocket)
        except Exception:  # noqa: BLE001
            logger.exception("ws remove_connection failed")


# ---------------- 文本消息分发 ----------------


async def _handle_text_message(
    manager: SessionManager,
    websocket: WebSocket,
    session_id: int,
    text: str,
) -> bool:
    """处理一条 text frame。返回 True 表示主循环应当 break（如收到 stop）。"""
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        await _send_error(websocket, "BAD_JSON", "Invalid JSON")
        return False

    if not isinstance(msg, dict):
        await _send_error(websocket, "BAD_JSON", "Expected JSON object")
        return False

    msg_type = msg.get("type")

    if msg_type == "ping":
        await _safe_send(websocket, {"type": "pong"})
        return False

    if msg_type == "stop":
        # 标 DB ended（短 session）
        db = SessionLocal()
        try:
            sess = (
                db.query(SessionModel)
                .filter(SessionModel.id == session_id)
                .one_or_none()
            )
            if sess is not None and sess.status == "active":
                sess.status = "ended"
                sess.ended_at = datetime.utcnow()
                sess.end_reason = "user_stop"
                db.commit()
        finally:
            db.close()
        # 起独立 task 跑 manager.stop —— 不能在当前 receive 循环里 await，
        # 否则 stop 广播 + 关闭所有 ws（含本 ws）会撕裂当前协程。
        asyncio.create_task(manager.stop(session_id, reason="user_stop"))
        return True  # break 主循环；finally 走 remove_connection

    if msg_type == "ask":
        qa_id_raw = msg.get("qa_id")
        try:
            qa_id = int(qa_id_raw)
        except (TypeError, ValueError):
            await _send_error(websocket, "BAD_QA_ID", "qa_id must be int")
            return False
        question = _load_qa_question(session_id, qa_id)
        if question is None:
            await _send_error(websocket, "QA_NOT_FOUND", "qa_id not found")
            return False
        asyncio.create_task(_run_ask(manager, session_id, qa_id, question))
        return False

    if msg_type == "ask_manual":
        raw_text = (msg.get("text") or "").strip()
        if not raw_text:
            await _send_error(websocket, "EMPTY_QUESTION", "text is empty")
            return False
        qa_id = _insert_manual_qa(session_id, raw_text)
        if qa_id is None:
            await _send_error(
                websocket, "QA_INSERT_FAILED", "could not insert manual qa"
            )
            return False
        asked_at = time.time()
        await manager.append_question(session_id, qa_id, raw_text, asked_at)
        await manager.broadcast(
            session_id,
            {
                "type": "question_added",
                "qa_id": qa_id,
                "text": raw_text,
                "asked_at": asked_at,
            },
        )
        asyncio.create_task(_run_ask(manager, session_id, qa_id, raw_text))
        return False

    await _send_error(
        websocket, "UNKNOWN_TYPE", f"Unknown message type: {msg_type!r}"
    )
    return False


# ---------------- LLM 三段并行 ----------------


async def _run_ask(
    manager: SessionManager,
    session_id: int,
    qa_id: int,
    question: str,
) -> None:
    """跑 LLM 三段流并 broadcast 每个事件；结束时回填 ``session_qa.answer_*``。"""
    # configs 库里 llm.providers / llm.default 是两条独立行，没有 llm 父 key
    cfg = {
        "providers": configs_module.get("llm.providers", []),
        "default": configs_module.get("llm.default", ""),
    }
    if not cfg["providers"] or not cfg["default"]:
        await manager.broadcast(
            session_id,
            {
                "type": "answer_error",
                "qa_id": qa_id,
                "segment": "all",
                "error": "LLM not configured",
            },
        )
        return

    try:
        service = LLMService(cfg)
    except Exception as e:  # noqa: BLE001
        await manager.broadcast(
            session_id,
            {
                "type": "answer_error",
                "qa_id": qa_id,
                "segment": "all",
                "error": str(e),
            },
        )
        return

    segments_text = {"key_points": "", "script": "", "full": ""}

    try:
        async for ev in service.stream_three_segments(question):
            if ev.type == "start":
                await manager.broadcast(
                    session_id,
                    {
                        "type": "answer_start",
                        "qa_id": qa_id,
                        "segment": ev.name,
                    },
                )
            elif ev.type == "chunk":
                segments_text[ev.name] = (
                    segments_text.get(ev.name, "") + ev.text
                )
                await manager.update_answer_chunk(
                    session_id, qa_id, ev.name, ev.text
                )
                await manager.broadcast(
                    session_id,
                    {
                        "type": "answer_chunk",
                        "qa_id": qa_id,
                        "segment": ev.name,
                        "text": ev.text,
                    },
                )
            elif ev.type == "end":
                await manager.mark_answer_segment_done(session_id, qa_id, ev.name)
                await manager.broadcast(
                    session_id,
                    {
                        "type": "answer_end",
                        "qa_id": qa_id,
                        "segment": ev.name,
                    },
                )
            elif ev.type == "error":
                await manager.broadcast(
                    session_id,
                    {
                        "type": "answer_error",
                        "qa_id": qa_id,
                        "segment": ev.name,
                        "error": ev.text,
                    },
                )
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("_run_ask crashed for session=%d qa=%d", session_id, qa_id)
        await manager.broadcast(
            session_id,
            {
                "type": "answer_error",
                "qa_id": qa_id,
                "segment": "all",
                "error": str(e),
            },
        )
        return

    # 三段都跑完，回填 DB
    db = SessionLocal()
    try:
        qa = db.query(SessionQA).filter(SessionQA.id == qa_id).one_or_none()
        if qa is not None:
            qa.answer_key_points = segments_text["key_points"]
            qa.answer_script = segments_text["script"]
            qa.answer_full = segments_text["full"]
            qa.finished_at = datetime.utcnow()
            db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("write back qa answers failed qa_id=%d", qa_id)
    finally:
        db.close()

    await manager.finalize_answer(session_id)


# ---------------- ASR forward task ----------------


async def _ensure_asr_started(
    manager: SessionManager, session_id: int, runtime: Any
) -> None:
    """会话第一个连接进来时启动 ASR client + forward task；其他连接 no-op。

    使用 runtime._lock 防多个连接并发 race。
    """
    async with runtime._lock:
        if runtime.asr_client is None:
            cfg = configs_module.get("asr.volcengine", {})
            try:
                client = VolcengineASRClient(cfg if isinstance(cfg, dict) else {})
                await client.start()
                runtime.asr_client = client
            except Exception:  # noqa: BLE001
                logger.exception("ASR client start failed for session %d", session_id)
                runtime.asr_client = None
        if (
            runtime.asr_forward_task is None
            or runtime.asr_forward_task.done()
        ) and runtime.asr_client is not None:
            runtime.asr_forward_task = asyncio.create_task(
                _asr_forward(manager, session_id, runtime.asr_client)
            )


async def _asr_forward(
    manager: SessionManager, session_id: int, asr_client: Any
) -> None:
    """会话级 ASR 事件 forward：partial/final/error → broadcast + 检测 question。"""
    detector = QuestionDetector(min_chars=6)
    try:
        async for ev in asr_client.stream_results():
            if ev.type == "partial":
                await manager.update_partial(session_id, ev.text)
                await manager.broadcast(
                    session_id,
                    {"type": "transcript_partial", "text": ev.text},
                )
            elif ev.type == "final":
                await manager.append_final(session_id, ev.text, ev.ts)
                await manager.broadcast(
                    session_id,
                    {
                        "type": "transcript_final",
                        "text": ev.text,
                        "ts": ev.ts,
                    },
                )
                # 短 session 走 question_handler
                db = SessionLocal()
                try:
                    await handle_asr_final(
                        db=db,
                        manager=manager,
                        session_id=session_id,
                        text=ev.text,
                        ts=ev.ts,
                        detector=detector,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "handle_asr_final crashed session=%d", session_id
                    )
                finally:
                    db.close()
            elif ev.type == "error":
                await manager.broadcast(
                    session_id,
                    {
                        "type": "error",
                        "code": "ASR_ERROR",
                        "message": ev.text,
                    },
                )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("asr_forward crashed for session %d", session_id)


# ---------------- 内部 helpers ----------------


def _get_manager() -> SessionManager:
    """允许测试 monkeypatch ``app.sessions.ws._get_manager``。生产用 module-level 单例。"""
    return default_manager


def _load_qa_question(session_id: int, qa_id: int) -> str | None:
    db = SessionLocal()
    try:
        qa = (
            db.query(SessionQA)
            .filter(SessionQA.id == qa_id, SessionQA.session_id == session_id)
            .one_or_none()
        )
        if qa is None:
            return None
        return qa.question
    finally:
        db.close()


def _insert_manual_qa(session_id: int, text: str) -> int | None:
    db = SessionLocal()
    try:
        qa = SessionQA(session_id=session_id, question=text, source="manual")
        db.add(qa)
        db.commit()
        db.refresh(qa)
        return qa.id
    except Exception:  # noqa: BLE001
        logger.exception(
            "insert manual qa failed session=%d", session_id
        )
        return None
    finally:
        db.close()


async def _safe_send(websocket: WebSocket, msg: dict) -> None:
    try:
        await websocket.send_text(json.dumps(msg, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        logger.debug("ws send_text failed (ignored)")


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    await _safe_send(
        websocket,
        {"type": "error", "code": code, "message": message},
    )
