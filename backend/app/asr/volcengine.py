"""火山引擎大模型流式 ASR — async 接口版本

接口（一会话一实例）：
  client = VolcengineASRClient(cfg)
  await client.start()
  await client.feed_pcm(pcm_bytes)             # 16kHz mono Int16 PCM 字节
  async for ev in client.stream_results(): ... # ASREvent 流（partial / final / error）
  await client.close()                         # 幂等

cfg 是 dict，调用方从 configs.get("asr.volcengine", {}) 取后传入：
  {"app_key": ..., "access_key": ..., "resource_id": ...}
"""
import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from volcengine_audio import VolcengineAsrFunctionsV3

# 火山引擎是国内服务，绕过代理直连
os.environ.setdefault("NO_PROXY", "openspeech.bytedance.com")
os.environ.setdefault("no_proxy", "openspeech.bytedance.com")


logger = logging.getLogger(__name__)


@dataclass
class ASREvent:
    """ASR 事件 —— 通过 stream_results() 异步推给消费者。"""

    type: str  # 'partial' | 'final' | 'error'
    text: str
    ts: float


class VolcengineASRClient:
    """火山引擎大模型流式语音识别（async 版本）。

    持久 WebSocket 连接，外部按帧 feed PCM 字节，识别结果以 ASREvent 异步推出。
    内部使用 asyncio.Queue 解耦生产/消费；不再依赖 threading 或 callback。
    """

    WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

    _SENTENCE_ENDERS = "。！？!?；;\n"
    _NORMALIZE_STRIP = re.compile(r"[\s。！？!?，,\.;；：:、\"'""''【】\[\]()()\-]+")
    MAX_RECENT_FINALS = 30

    def __init__(self, cfg: dict):
        self.app_key = cfg.get("app_key", "")
        self.access_key = cfg.get("access_key", "")
        self.resource_id = cfg.get("resource_id", "volc.bigasr.sauc.duration")

        self._ws = None
        self._seq = 0
        self._connected = False
        self._closed = False

        # 内部事件队列：_session 写入，stream_results() 读出
        self._events: asyncio.Queue[ASREvent] = asyncio.Queue()
        # 主连接循环 task（含重连逻辑）
        self._main_task: Optional[asyncio.Task] = None
        # 控制 stop 的 Event；close() 时 set，_connect_loop 据此退出
        self._stop_event = asyncio.Event()

        # 业务状态：会话内已 final 的文本前缀 + 最近 final 句子归一化集合，用于去重
        self._committed = ""
        self._recent_finals: list[str] = []

    # ---------- 公共 API ----------

    async def start(self) -> None:
        """启动后台连接 task。重复调用幂等（已启动则忽略）。"""
        if self._main_task is not None and not self._main_task.done():
            return
        self._closed = False
        self._stop_event.clear()
        self._main_task = asyncio.create_task(self._connect_loop())

    async def feed_pcm(self, frame: bytes) -> None:
        """喂一帧 PCM 字节。未连接时静默丢弃（不抛）。

        frame 应为 16kHz mono Int16 PCM 原始字节流（前端 AudioWorklet 已处理好）。
        """
        if self._closed or not self._connected or self._ws is None:
            return
        try:
            await self._send_audio(frame)
        except Exception as e:  # noqa: BLE001
            # 单帧发送失败不致命；连接异常会由 _session 自身捕获并触发重连
            logger.debug("feed_pcm send error: %s", e)

    async def stream_results(self) -> AsyncIterator[ASREvent]:
        """异步迭代 ASR 事件。close() 后会自然结束。"""
        while not self._closed:
            try:
                event = await self._events.get()
            except asyncio.CancelledError:
                break
            yield event

    async def close(self) -> None:
        """优雅关闭：取消主 task，关闭 WS。幂等，可重复调用。"""
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()

        # 主动关 ws，让 recv_loop 立刻退出
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None

        if self._main_task is not None:
            self._main_task.cancel()
            try:
                await self._main_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._main_task = None

        self._connected = False

    # ---------- 内部：连接 / 收发 ----------

    async def _connect_loop(self) -> None:
        """带重连的主循环。"""
        retry_delays = [1, 2, 4]
        retry_count = 0

        while not self._stop_event.is_set():
            try:
                await self._session()
                retry_count = 0
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                self._connected = False
                if self._stop_event.is_set():
                    break
                if retry_count < len(retry_delays):
                    delay = retry_delays[retry_count]
                    retry_count += 1
                    await self._emit_error(
                        f"ASR 连接断开，{delay}s 后重连 ({retry_count}/3)"
                    )
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=delay
                        )
                        break  # stop 期间被 set，退出
                    except asyncio.TimeoutError:
                        pass  # 继续下一轮重连
                else:
                    await self._emit_error(f"ASR 重连失败: {e}")
                    break

    async def _session(self) -> None:
        """单次 WebSocket 会话：握手 → 收发循环。"""
        import websockets

        headers = {
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
        }

        async with websockets.connect(
            self.WS_URL,
            additional_headers=headers,
            max_size=None,
            ping_interval=20,
            ping_timeout=10,
            proxy=None,
        ) as ws:
            self._ws = ws
            self._seq = 1

            request_params = {
                "user": {},
                "audio": {
                    "format": "pcm",
                    "codec": "raw",
                    "rate": 16000,
                    "bits": 16,
                    "channel": 1,
                },
                "request": {
                    "model_name": "bigmodel",
                    "enable_itn": True,
                    "enable_punc": True,
                    "result_type": "full",
                },
            }

            full_req = VolcengineAsrFunctionsV3.generate_asr_full_client_request(
                sequence=self._seq,
                request_params=request_params,
                compression=True,
            )
            await ws.send(full_req)
            res = await ws.recv()
            parsed = VolcengineAsrFunctionsV3.parse_response(res)
            if "code" in parsed and parsed["code"] != 0:
                raise RuntimeError(f"服务端错误: {parsed}")

            self._seq = 2
            self._connected = True
            self._committed = ""
            self._recent_finals = []
            logger.info("[asr] 火山引擎流式 ASR 已连接")

            await self._recv_loop(ws)

    async def _recv_loop(self, ws) -> None:
        """持续读取服务端推送的识别结果。"""
        while not self._stop_event.is_set():
            try:
                res = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                break

            parsed = VolcengineAsrFunctionsV3.parse_response(res)

            if "code" in parsed and parsed["code"] != 0:
                await self._emit_error(f"ASR 错误: {parsed}")
                continue

            if "message" not in parsed:
                continue

            msg = parsed["message"]
            if not isinstance(msg, dict):
                continue

            result = msg.get("result", {})
            text = result.get("text", "") if isinstance(result, dict) else ""

            if parsed.get("is_last_package"):
                tail = self._tail(text)
                if tail:
                    await self._emit_finals_dedup(tail)
                self._committed = ""
            elif text:
                await self._segment(text)

    async def _send_audio(self, pcm_bytes: bytes) -> None:
        """发送一帧音频。"""
        if not self._ws or not self._connected:
            return
        try:
            audio_req = VolcengineAsrFunctionsV3.generate_asr_audio_only_request(
                sequence=self._seq,
                audio=pcm_bytes,
                compress=True,
            )
            await self._ws.send(audio_req)
            self._seq += 1
        except Exception:  # noqa: BLE001
            self._connected = False

    # ---------- 内部：业务逻辑（去重 / 分段）----------

    def _tail(self, text: str) -> str:
        """返回 text 中尚未作为 final 推出的尾部。"""
        if text.startswith(self._committed):
            return text[len(self._committed):]
        # 前缀不匹配：服务端改写了早先文本。找 LCP，缩到共同前缀
        lcp_len = 0
        for i in range(min(len(self._committed), len(text))):
            if self._committed[i] != text[i]:
                break
            lcp_len += 1
        self._committed = self._committed[:lcp_len]
        return text[lcp_len:]

    async def _segment(self, text: str) -> None:
        """按句末标点切分：已完成的句子走 final（去重），剩余尾巴走 partial。"""
        if not text.startswith(self._committed):
            lcp_len = 0
            for i in range(min(len(self._committed), len(text))):
                if self._committed[i] != text[i]:
                    break
                lcp_len += 1
            self._committed = self._committed[:lcp_len]

        start = len(self._committed)
        last_boundary = -1
        for i in range(start, len(text)):
            if text[i] in self._SENTENCE_ENDERS:
                last_boundary = i

        if last_boundary >= start:
            finalized = text[start:last_boundary + 1]
            await self._emit_finals_dedup(finalized)
            self._committed = text[:last_boundary + 1]

        tail = text[len(self._committed):]
        await self._emit_partial(tail)

    async def _emit_finals_dedup(self, chunk: str) -> None:
        """把 chunk 按句末标点切成单句，每句归一化后查重，未见过才 emit。"""
        sentences = self._split_sentences(chunk)
        for sentence in sentences:
            s = sentence.strip()
            if not s:
                continue
            norm = self._normalize(s)
            if not norm:
                continue
            if norm in self._recent_finals:
                continue
            self._recent_finals.append(norm)
            if len(self._recent_finals) > self.MAX_RECENT_FINALS:
                self._recent_finals.pop(0)
            await self._emit_final(s)

    @classmethod
    def _split_sentences(cls, text: str) -> list[str]:
        """按句末标点切成 [句1, 句2, ...]，每句带尾标点。尾部无标点的残片单独作为一项。"""
        parts: list[str] = []
        buf = ""
        for ch in text:
            buf += ch
            if ch in cls._SENTENCE_ENDERS:
                parts.append(buf)
                buf = ""
        if buf:
            parts.append(buf)
        return parts

    @classmethod
    def _normalize(cls, s: str) -> str:
        return cls._NORMALIZE_STRIP.sub("", s).lower()

    # ---------- 内部：事件投递 ----------

    async def _emit_partial(self, text: str) -> None:
        await self._events.put(ASREvent(type="partial", text=text, ts=time.time()))

    async def _emit_final(self, text: str) -> None:
        await self._events.put(ASREvent(type="final", text=text, ts=time.time()))

    async def _emit_error(self, text: str) -> None:
        await self._events.put(ASREvent(type="error", text=text, ts=time.time()))
