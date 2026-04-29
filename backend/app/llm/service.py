"""LLM service：三段并行流（key_points / script / full）+ 真取消。

设计要点：
- 复用 app/llm/__init__.py 里的 LLMProvider 抽象（同步 generator）
- 用 asyncio.to_thread + sync_iter.close() 桥接 sync→async，aclose() 时关底层 HTTP
- fan-out 三段：每段一个独立 task 推到共享 out_queue，主 generator 多路输出
- 任意 segment 抛错 → 推 error 事件，其他段继续；aclose() → 取消所有子任务

调用方拿到的接口：
    service = LLMService(configs_dict)
    async for ev in service.stream_three_segments("解释什么是B+树"):
        ...  # ev: LLMEvent(name='key_points'|'script'|'full',
             #              type='start'|'chunk'|'end'|'error', text=...)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Iterator

from app.llm import (
    SECTION_PROMPTS,
    ClaudeProvider,
    DeepSeekProvider,
    GeminiProvider,
    GrokProvider,
    LLMProvider,
    OpenAIProvider,
)


logger = logging.getLogger(__name__)


_SENTINEL = object()  # 用于 next(it, default) 探测耗尽


_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "grok": GrokProvider,
    "gemini": GeminiProvider,
    "deepseek": DeepSeekProvider,
}


@dataclass
class LLMEvent:
    """三段流统一事件。

    name: 段名（'key_points' | 'script' | 'full'）
    type: 'start' | 'chunk' | 'end' | 'error'
    text: chunk 的文本内容；error 时是错误信息；start/end 一般为空
    """

    name: str
    type: str
    text: str = ""


class LLMService:
    """LLM 三段并行流服务。

    构造时只需配置 dict（不依赖 app.configs 模块，方便测试）：
        {
          "providers": [
            {"name": "deepseek", "api_key": "sk-...", "model": "deepseek-chat"},
            {"name": "claude",   "api_key": "sk-...", "model": "claude-sonnet-4-5"}
          ],
          "default": "deepseek"
        }
    """

    def __init__(self, configs_dict: dict):
        providers = configs_dict.get("providers") or []
        default_name = configs_dict.get("default")
        if not default_name:
            raise RuntimeError("LLM default provider not configured")

        entry = next(
            (p for p in providers if p.get("name") == default_name),
            None,
        )
        if entry is None:
            raise RuntimeError(
                f"LLM provider {default_name} not configured"
            )

        cls = _PROVIDER_REGISTRY.get(default_name)
        if cls is None:
            raise RuntimeError(
                f"Unknown LLM provider type: {default_name}"
            )

        # 保存 cfg 而非单一 provider 实例：每段流单独 build provider，
        # 避免 3 段并行共享同一个 HTTP client 时的连接池冲突
        self._provider_cls = cls
        self._provider_cfg = {
            "api_key": entry.get("api_key"),
            "model": entry.get("model"),
        }
        self.provider_name = default_name
        # 兼容老测试：暴露一个默认 provider 实例
        self.provider: LLMProvider = cls(self._provider_cfg)

    def _build_provider(self) -> LLMProvider:
        """每段 segment 独立 build，避免共享 client 连接池竞争。"""
        return self._provider_cls(self._provider_cfg)

    async def _stream_segment(
        self, name: str, question: str
    ) -> AsyncIterator[LLMEvent]:
        """跑一段 segment：start → chunks → end / error。

        finally 块里 sync_iter.close() 触发底层 generator 的 finally
        （DeepSeekProvider 会关 HTTP stream），保证取消时资源释放。
        """
        yield LLMEvent(name=name, type="start")
        logger.info("[llm] segment %s starting", name)

        system_prompt = SECTION_PROMPTS[name]
        sync_iter: Iterator[str] | None = None
        chunk_count = 0
        try:
            try:
                # 每段独立 provider 实例，避免共享 HTTP client 并发冲突
                provider = self._build_provider()
                sync_iter = provider.ask_stream(question, system_prompt)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "llm segment %s: ask_stream init failed: %s", name, e
                )
                yield LLMEvent(name=name, type="error", text=str(e))
                return

            while True:
                try:
                    chunk = await asyncio.to_thread(
                        next, sync_iter, _SENTINEL
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "llm segment %s: stream error after %d chunks: %s",
                        name, chunk_count, e
                    )
                    yield LLMEvent(name=name, type="error", text=str(e))
                    return

                if chunk is _SENTINEL:
                    break
                if chunk:
                    chunk_count += 1
                    yield LLMEvent(name=name, type="chunk", text=chunk)

            logger.info("[llm] segment %s done (chunks=%d)", name, chunk_count)
            yield LLMEvent(name=name, type="end")
        finally:
            # GeneratorExit / Cancel：关同步 generator
            # （会触发 DeepSeekProvider.ask_stream 里的 finally → stream.close()）
            if sync_iter is not None:
                try:
                    sync_iter.close()
                except Exception:  # noqa: BLE001
                    pass

    async def stream_three_segments(
        self, question: str
    ) -> AsyncIterator[LLMEvent]:
        """三段并行流。

        - 任意 segment 抛错只推 error 事件，其他段继续
        - 调用方对返回 generator 调 aclose() → 立即取消所有子任务
          → 每个 _stream_segment 的 finally 关 sync_iter → 关 HTTP
        """
        segments = ["key_points", "script", "full"]
        out_queue: asyncio.Queue = asyncio.Queue()
        done_sentinel = object()

        async def consumer(seg: str) -> None:
            try:
                async for ev in self._stream_segment(seg, question):
                    await out_queue.put(ev)
            except asyncio.CancelledError:
                # 上面 await 被 cancel → _stream_segment 的 finally 已关 sync_iter
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("llm segment %s consumer crashed", seg)
                try:
                    await out_queue.put(
                        LLMEvent(name=seg, type="error", text=str(e))
                    )
                except Exception:  # noqa: BLE001
                    pass
            finally:
                try:
                    await out_queue.put(done_sentinel)
                except Exception:  # noqa: BLE001
                    pass

        tasks = [asyncio.create_task(consumer(s)) for s in segments]

        try:
            finished = 0
            while finished < len(segments):
                item = await out_queue.get()
                if item is done_sentinel:
                    finished += 1
                    continue
                yield item
        finally:
            # GeneratorExit / aclose() → 取消所有子任务
            for t in tasks:
                if not t.done():
                    t.cancel()
            # 等所有 task 跑完 finally（关 sync_iter）
            await asyncio.gather(*tasks, return_exceptions=True)
