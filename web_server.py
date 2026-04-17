"""
Web 镜像 UI 桥接层。

在 Qt 进程里起一个后台线程跑 asyncio + aiohttp，把 Worker 的信号广播给
浏览器，同时接受浏览器的发问命令转回 Worker。

关键线程模型：
- Qt 主线程：UI + Worker 信号。
- asyncio 线程：aiohttp HTTP + WebSocket。

Qt → asyncio：`_schedule_broadcast()` 用 `loop.call_soon_threadsafe` 把事件
丢进 asyncio 队列。

asyncio → Qt：WebSocket 收到命令后 `self.ask_requested.emit(text)`，
在 main.py 里以 `Qt.QueuedConnection` 连到 worker.ask（跨线程自动安全）。
"""

import asyncio
import json
import socket
import threading
from pathlib import Path

from aiohttp import web, WSMsgType
from PySide6.QtCore import QObject, Signal, Qt

WEB_DIR = Path(__file__).parent / "web"


def _score_ip(ip: str) -> int:
    """越大越像真实局域网 IP。"""
    try:
        parts = [int(x) for x in ip.split(".")]
        if len(parts) != 4:
            return -1
        a, b, c, d = parts
    except Exception:
        return -1
    if a == 127:
        return -1
    if a == 198 and b in (18, 19):
        return -1  # RFC2544 benchmark，常见于 ClashX / Surge 代理
    if a == 169 and b == 254:
        return 0   # link-local
    if a == 192 and b == 168:
        return 5   # 家用路由最典型
    if a == 10:
        return 4
    if a == 172 and 16 <= b <= 31:
        return 4
    return 1       # 公网或其他


def get_lan_ip() -> str | None:
    """尽力找出真实局域网 IP；代理 / VPN 环境下会过滤 198.18/15 等虚假地址。"""
    candidates: list[str] = []

    # 1) UDP 路由表技巧（可能被 VPN 拦截）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        candidates.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    # 2) hostname 解析（Mac 常能给出多个网卡 IP）
    try:
        hostname = socket.gethostname()
        _, _, ips = socket.gethostbyname_ex(hostname)
        candidates.extend(ips)
    except Exception:
        pass

    # 3) mDNS .local 兜底（Mac 一般可用）
    try:
        hostname = socket.gethostname()
        if not hostname.endswith(".local"):
            hostname = hostname + ".local"
        ip = socket.gethostbyname(hostname)
        candidates.append(ip)
    except Exception:
        pass

    # 打分挑最像局域网的
    best = None
    best_score = 0
    for ip in candidates:
        if not ip or ip == "0.0.0.0":
            continue
        score = _score_ip(ip)
        if score > best_score:
            best = ip
            best_score = score
    return best


class WebBridge(QObject):
    # 由 asyncio 线程 emit → Qt 线程 slot（QueuedConnection）
    ask_requested = Signal(str)

    # 历史快照上限
    MAX_TRANSCRIPT = 80
    MAX_QUESTIONS = 100

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        super().__init__()
        self.host = host
        self.port = port

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._runner: web.AppRunner | None = None
        self._clients: set[web.WebSocketResponse] = set()

        # 状态快照（供新客户端连上时补齐）
        self._state = {
            "status": "未启动",
            "transcript_finals": [],     # list[str]
            "transcript_partial": "",
            "questions": [],             # list[{"text": str, "state": "pending"|"asked"}]
            "current_answer": None,      # {"question": str, "sections": {...}, "non_question": bool}
        }
        self._state_lock = threading.Lock()

    # ============ 生命周期 ============

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        ready = threading.Event()

        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._startup(ready))
                self._loop.run_forever()
            finally:
                try:
                    self._loop.run_until_complete(self._shutdown())
                except Exception:
                    pass
                self._loop.close()

        self._thread = threading.Thread(target=run, name="WebBridge", daemon=True)
        self._thread.start()
        ready.wait(timeout=5)

    def stop(self):
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=2)

    async def _startup(self, ready: threading.Event):
        app = web.Application()
        app.router.add_get("/", self._serve_index)
        app.router.add_get("/ws", self._ws_handler)
        app.router.add_static("/static", WEB_DIR, show_index=False)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        print(f"[web] listening on http://{self.host}:{self.port}")
        if self.host in ("0.0.0.0", "::"):
            lan = get_lan_ip()
            if lan:
                print(f"[web] LAN (同 WiFi 手机可访问): http://{lan}:{self.port}")
        ready.set()

    async def _shutdown(self):
        # 关所有 ws
        for ws in list(self._clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()
        if self._runner:
            await self._runner.cleanup()

    # ============ HTTP handlers ============

    async def _serve_index(self, request):
        index = WEB_DIR / "index.html"
        if not index.exists():
            return web.Response(status=500, text="index.html missing")
        return web.FileResponse(index)

    async def _ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=25)
        await ws.prepare(request)
        self._clients.add(ws)

        # 先发 snapshot
        with self._state_lock:
            snapshot = {"type": "snapshot", "state": json.loads(json.dumps(self._state))}
        try:
            await ws.send_json(snapshot)
        except Exception:
            self._clients.discard(ws)
            return ws

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    self._handle_client_msg(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            self._clients.discard(ws)
        return ws

    def _handle_client_msg(self, raw: str):
        try:
            m = json.loads(raw)
        except Exception:
            return
        t = m.get("type")
        if t == "ask":
            text = (m.get("text") or "").strip()
            if text:
                self.ask_requested.emit(text)
        elif t == "mark_asked":
            idx = m.get("index")
            if isinstance(idx, int):
                with self._state_lock:
                    if 0 <= idx < len(self._state["questions"]):
                        self._state["questions"][idx]["state"] = "asked"
                self._schedule_broadcast({"type": "question_asked", "index": idx})

    # ============ 广播核心 ============

    def _broadcast_now(self, msg: dict):
        """在 asyncio 线程内执行：发给所有 ws。"""
        dead = []
        data = json.dumps(msg, ensure_ascii=False)
        for ws in list(self._clients):
            if ws.closed:
                dead.append(ws)
                continue
            try:
                asyncio.create_task(ws.send_str(data))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def _schedule_broadcast(self, msg: dict):
        """线程安全入口：从 Qt 线程调用，把广播丢到 asyncio loop。"""
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        loop.call_soon_threadsafe(self._broadcast_now, msg)

    # ============ Qt 信号槽（在 Qt 主线程执行） ============

    def on_status(self, text: str):
        with self._state_lock:
            self._state["status"] = text
        self._schedule_broadcast({"type": "status", "text": text})

    def on_partial(self, text: str):
        with self._state_lock:
            self._state["transcript_partial"] = text
        self._schedule_broadcast({"type": "partial", "text": text})

    def on_final(self, text: str):
        with self._state_lock:
            self._state["transcript_partial"] = ""
            self._state["transcript_finals"].append(text)
            if len(self._state["transcript_finals"]) > self.MAX_TRANSCRIPT:
                self._state["transcript_finals"] = self._state["transcript_finals"][-self.MAX_TRANSCRIPT:]
        self._schedule_broadcast({"type": "final", "text": text})

    def on_question_ready(self, text: str):
        with self._state_lock:
            self._state["questions"].append({"text": text, "state": "pending"})
            if len(self._state["questions"]) > self.MAX_QUESTIONS:
                overflow = len(self._state["questions"]) - self.MAX_QUESTIONS
                self._state["questions"] = self._state["questions"][overflow:]
            idx = len(self._state["questions"]) - 1
        self._schedule_broadcast({"type": "question_added", "index": idx, "text": text})

    def on_answer_started(self, question: str):
        # 反推：把 questions 里最后一条 text == question 且 pending 的标成 asked
        asked_idx = None
        with self._state_lock:
            for i in range(len(self._state["questions"]) - 1, -1, -1):
                q = self._state["questions"][i]
                if q["text"] == question and q["state"] == "pending":
                    q["state"] = "asked"
                    asked_idx = i
                    break
            self._state["current_answer"] = {
                "question": question,
                "sections": {
                    "key_points": {"state": "idle", "text": ""},
                    "script":     {"state": "idle", "text": ""},
                    "full":       {"state": "idle", "text": ""},
                },
                "non_question": False,
            }
        if asked_idx is not None:
            self._schedule_broadcast({"type": "question_asked", "index": asked_idx})
        self._schedule_broadcast({"type": "answer_started", "question": question})

    def on_section_start(self, name: str):
        with self._state_lock:
            ca = self._state["current_answer"]
            if ca and name in ca["sections"]:
                ca["sections"][name]["state"] = "streaming"
        self._schedule_broadcast({"type": "section_start", "name": name})

    def on_section_chunk(self, name: str, text: str):
        with self._state_lock:
            ca = self._state["current_answer"]
            if ca and name in ca["sections"]:
                ca["sections"][name]["text"] += text
        self._schedule_broadcast({"type": "section_chunk", "name": name, "text": text})

    def on_section_end(self, name: str):
        with self._state_lock:
            ca = self._state["current_answer"]
            if ca and name in ca["sections"]:
                ca["sections"][name]["state"] = "done"
        self._schedule_broadcast({"type": "section_end", "name": name})

    def on_answer_non_question(self):
        with self._state_lock:
            ca = self._state["current_answer"]
            if ca:
                ca["non_question"] = True
        self._schedule_broadcast({"type": "answer_non_question"})

    def on_error(self, msg: str):
        self._schedule_broadcast({"type": "error", "text": msg})
