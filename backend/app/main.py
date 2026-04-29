"""FastAPI 入口。"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import configs
from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.config import settings
from app.db import SessionLocal
from app.logging_config import setup_logging
from app.recharge.admin_router import router as recharge_admin_router
from app.recharge.router import router as recharge_router
from app.sessions.router import router as sessions_router
from app.sessions.ws import ws_router
from app.users.router import router as users_router


# 进程启动即配好；FastAPI lifespan 触发前 import-time 已完成
setup_logging()
_log = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log.info(
        "startup",
        extra={"env": settings.env, "log_level": settings.log_level},
    )
    # Startup: load configs cache, start background watcher
    db = SessionLocal()
    try:
        configs.init_cache(db)
    finally:
        db.close()
    loop = asyncio.get_running_loop()
    configs.start_watcher(loop)
    try:
        yield
    finally:
        _log.info("shutdown")
        await configs.stop_watcher()


app = FastAPI(title="Interview Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True, "env": settings.env}


@app.get("/api/health/db")
def health_db():
    """测 DB 连通性。失败返回 503，方便外部探针。"""
    from sqlalchemy import text

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        _log.warning("health/db failed: %s", exc)
        from fastapi import HTTPException, status as http_status

        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "DB_UNAVAILABLE", "message": "数据库连接失败"}},
        )
    finally:
        db.close()


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(billing_router)
app.include_router(recharge_router)
app.include_router(recharge_admin_router)
app.include_router(sessions_router)
app.include_router(ws_router)
app.include_router(admin_router)
