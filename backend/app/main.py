"""FastAPI 入口。"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import configs
from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.config import settings
from app.db import SessionLocal
from app.recharge.router import router as recharge_router
from app.sessions.router import router as sessions_router
from app.sessions.ws import ws_router
from app.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
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


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(billing_router)
app.include_router(recharge_router)
app.include_router(sessions_router)
app.include_router(ws_router)
app.include_router(admin_router)
