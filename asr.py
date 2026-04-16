import asyncio
import os
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
                if text:
                    self.on_final(text)
            elif text:
                self.on_partial(text)

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
