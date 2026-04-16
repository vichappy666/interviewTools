import asyncio
import os
import re
import threading
import numpy as np
from volcengine_audio import VolcengineAsrFunctionsV3

# 火山引擎是国内服务，绕过代理直连
os.environ.setdefault("NO_PROXY", "openspeech.bytedance.com")
os.environ.setdefault("no_proxy", "openspeech.bytedance.com")


class StreamingASR:
    """
    火山引擎大模型流式语音识别。
    持久 WebSocket 连接，100ms 一帧实时发送，服务端推 partial/final result。
    """

    WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

    def __init__(self, cfg, on_partial, on_final, on_error):
        self.app_key = cfg.get("app_key", "")
        self.access_key = cfg.get("access_key", "")
        self.resource_id = cfg.get("resource_id", "volc.bigasr.sauc.duration")
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_error = on_error

        self._loop = None
        self._thread = None
        self._ws = None
        self._seq = 0
        self._connected = False
        self._stop_event = None
        self._committed = ""  # 当前会话中已作为 final 推出的前缀
        self._recent_finals = []  # 最近已 emit 的句子归一化形式，用于去重

    def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._connected = False
        if self._stop_event and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def feed(self, audio_chunk: np.ndarray):
        """外部每 100ms 调一次，传入 float32 音频数据"""
        if not self._connected or not self._loop:
            return
        pcm = (audio_chunk * 32767).astype(np.int16).tobytes()
        try:
            asyncio.run_coroutine_threadsafe(self._send_audio(pcm), self._loop)
        except Exception:
            pass

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self._connect_loop())
        except Exception:
            pass
        finally:
            # 清理所有pending tasks
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()
            self._loop = None

    async def _connect_loop(self):
        """带重连的主循环"""
        retry_delays = [1, 2, 4]
        retry_count = 0

        while not self._stop_event.is_set():
            try:
                await self._session()
                retry_count = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                if self._stop_event.is_set():
                    break
                if retry_count < len(retry_delays):
                    delay = retry_delays[retry_count]
                    retry_count += 1
                    self.on_error(f"ASR 连接断开，{delay}s 后重连 ({retry_count}/3)")
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                        break  # stop_event was set during wait
                    except asyncio.TimeoutError:
                        pass  # retry
                else:
                    self.on_error(f"ASR 重连失败: {e}")
                    break

    async def _session(self):
        """单次 WebSocket 会话"""
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
            print("[asr] 火山引擎流式 ASR 已连接")

            await self._recv_loop(ws)

    async def _recv_loop(self, ws):
        """持续读取服务端推送的识别结果"""
        while not self._stop_event.is_set():
            try:
                res = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                break

            parsed = VolcengineAsrFunctionsV3.parse_response(res)

            if "code" in parsed and parsed["code"] != 0:
                self.on_error(f"ASR 错误: {parsed}")
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
                    self._emit_finals_dedup(tail)
                self._committed = ""
            elif text:
                self._segment(text)

    _SENTENCE_ENDERS = "。！？!?；;\n"
    _NORMALIZE_STRIP = re.compile(r"[\s。！？!?，,\.;；：:、\"'""''【】\[\]（）()\-]+")
    MAX_RECENT_FINALS = 30

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

    def _segment(self, text: str):
        """按句末标点切分：已完成的句子走 on_final（去重），剩余尾巴走 on_partial。"""
        if not text.startswith(self._committed):
            # 服务端改写了历史文本；找 LCP 而不是全部重置
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
            self._emit_finals_dedup(finalized)
            self._committed = text[:last_boundary + 1]

        tail = text[len(self._committed):]
        self.on_partial(tail)

    def _emit_finals_dedup(self, chunk: str):
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
            self.on_final(s)

    @classmethod
    def _split_sentences(cls, text: str):
        """按句末标点切成 [句1, 句2, ...]，每句带尾标点。尾部无标点的残片单独作为一项。"""
        parts = []
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

    async def _send_audio(self, pcm_bytes: bytes):
        """发送一帧音频"""
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
        except Exception:
            self._connected = False
