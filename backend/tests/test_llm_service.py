"""Tests for app.llm.service.LLMService — 三段并行流 + 取消。

策略：mock provider，绝不连真 API。验证：
1. 三段都跑出 start...chunks...end
2. 三段并行（chunks 交叉到达）
3. 一段抛错 → 该段出 error，其他段正常完成
4. aclose() 取消所有段，sync generator 被 close
5. 配置选 default provider；找不到则 RuntimeError
"""
import asyncio

import pytest

from app.llm import SECTION_PROMPTS
from app.llm.service import LLMEvent, LLMService


# ---------------- mock provider ----------------

class MockProvider:
    """同步 generator 风格的 mock LLM provider。

    chunks_per_section: dict[system_prompt -> list[str]]
        映射 section 的 system prompt 到要 yield 的 chunks 列表。
    raise_on_prompts: set[system_prompt]
        指定哪些 prompt 进入 ask_stream 后立刻抛错。
    delay_per_chunk_per_section: dict[system_prompt -> float]
        每段每 chunk 之间的 sleep（用于让 chunks 交错到达）。
    """

    def __init__(
        self,
        chunks_per_section: dict[str, list[str]] | None = None,
        raise_on_prompts: set[str] | None = None,
        delay_per_chunk_per_section: dict[str, float] | None = None,
    ):
        self.chunks_per_section = chunks_per_section or {}
        self.raise_on_prompts = raise_on_prompts or set()
        self.delay_per_chunk_per_section = (
            delay_per_chunk_per_section or {}
        )
        self.close_count = 0
        self.start_count = 0

    def ask(self, question, system_prompt=None):  # pragma: no cover
        return "mock"

    def ask_stream(self, question, system_prompt=None):
        if system_prompt in self.raise_on_prompts:
            raise RuntimeError(f"mock error on prompt={system_prompt[:20]}")
        chunks = self.chunks_per_section.get(system_prompt, ["a", "b"])
        delay = self.delay_per_chunk_per_section.get(system_prompt, 0.0)
        return self._gen(chunks, delay)

    def _gen(self, chunks, delay):
        self.start_count += 1
        try:
            import time

            for c in chunks:
                if delay:
                    time.sleep(delay)
                yield c
        except GeneratorExit:
            self.close_count += 1
            raise
        finally:
            # 注：GeneratorExit 已经在上面分支记过；正常 return 也走这里
            pass


def _make_service_with_provider(provider) -> LLMService:
    """构造一个 LLMService，跳过 __init__ 真实 provider 路由，直接注入 mock。

    每段 _stream_segment 会调 _build_provider() 拿独立实例（生产环境避免连接池竞争），
    但测试里希望复用同一个 mock，所以 _build_provider 直接返回这个共享 provider。
    """
    svc = LLMService.__new__(LLMService)
    svc.provider = provider
    svc.provider_name = "mock"
    svc._build_provider = lambda: provider  # type: ignore[method-assign]
    return svc


# ---------------- 1. 全部跑完：三段都有 start/chunks/end ----------------

@pytest.mark.asyncio
async def test_three_segments_all_yield_start_chunks_end():
    provider = MockProvider(
        chunks_per_section={
            SECTION_PROMPTS["key_points"]: ["要点1 ", "要点2"],
            SECTION_PROMPTS["script"]: ["话术 ", "段"],
            SECTION_PROMPTS["full"]: ["详细 ", "答案"],
        }
    )
    svc = _make_service_with_provider(provider)

    events: list[LLMEvent] = []
    async for ev in svc.stream_three_segments("Q?"):
        events.append(ev)

    # 每段都至少出现一次 start / end
    by_name: dict[str, list[LLMEvent]] = {}
    for ev in events:
        by_name.setdefault(ev.name, []).append(ev)

    assert set(by_name.keys()) == {"key_points", "script", "full"}
    for name, evs in by_name.items():
        types = [e.type for e in evs]
        assert types[0] == "start", f"{name} 第一个事件应是 start"
        assert types[-1] == "end", f"{name} 最后一个事件应是 end"
        chunks = [e.text for e in evs if e.type == "chunk"]
        assert len(chunks) >= 1, f"{name} 至少要有 1 个 chunk"


# ---------------- 2. 并行：chunks 交叉到达 ----------------

@pytest.mark.asyncio
async def test_chunks_interleave():
    """三段并行跑：sleep 让 chunks 交错。最终 events 中三段的 chunk 应交叉。"""
    provider = MockProvider(
        chunks_per_section={
            SECTION_PROMPTS["key_points"]: ["k1", "k2", "k3"],
            SECTION_PROMPTS["script"]: ["s1", "s2", "s3"],
            SECTION_PROMPTS["full"]: ["f1", "f2", "f3"],
        },
        delay_per_chunk_per_section={
            SECTION_PROMPTS["key_points"]: 0.01,
            SECTION_PROMPTS["script"]: 0.01,
            SECTION_PROMPTS["full"]: 0.01,
        },
    )
    svc = _make_service_with_provider(provider)

    chunk_names: list[str] = []
    async for ev in svc.stream_three_segments("Q?"):
        if ev.type == "chunk":
            chunk_names.append(ev.name)

    # 三段交错应至少出现一次 "上一个 chunk 的 name 和当前不同"
    transitions = sum(
        1
        for i in range(1, len(chunk_names))
        if chunk_names[i] != chunk_names[i - 1]
    )
    assert transitions >= 2, (
        f"chunks 应交错到达，实际：{chunk_names}"
    )


# ---------------- 3. 一段抛错，其他段照常完成 ----------------

@pytest.mark.asyncio
async def test_segment_error_yields_error_event_others_continue():
    provider = MockProvider(
        chunks_per_section={
            SECTION_PROMPTS["key_points"]: ["k1", "k2"],
            SECTION_PROMPTS["full"]: ["f1", "f2"],
        },
        raise_on_prompts={SECTION_PROMPTS["script"]},
    )
    svc = _make_service_with_provider(provider)

    events: list[LLMEvent] = []
    async for ev in svc.stream_three_segments("Q?"):
        events.append(ev)

    # script 段：start + error，没有 end
    script_evs = [e for e in events if e.name == "script"]
    types = [e.type for e in script_evs]
    assert types[0] == "start"
    assert "error" in types
    assert "end" not in types
    err_ev = next(e for e in script_evs if e.type == "error")
    assert "mock error" in err_ev.text

    # 其他两段：有 end
    for name in ("key_points", "full"):
        evs = [e for e in events if e.name == name]
        assert any(e.type == "end" for e in evs), (
            f"{name} 应正常 end, 实际事件：{[e.type for e in evs]}"
        )


# ---------------- 4. aclose() 取消，sync generator 被 close ----------------

@pytest.mark.asyncio
async def test_aclose_cancels_all_segments():
    """生成 service 流；拿几个事件；aclose() → 检查 mock 的 close_count > 0。"""
    # 给每段 100 个 chunk + 较长 delay，确保来不及跑完
    big_chunks = [f"c{i}" for i in range(100)]
    provider = MockProvider(
        chunks_per_section={
            SECTION_PROMPTS["key_points"]: list(big_chunks),
            SECTION_PROMPTS["script"]: list(big_chunks),
            SECTION_PROMPTS["full"]: list(big_chunks),
        },
        delay_per_chunk_per_section={
            SECTION_PROMPTS["key_points"]: 0.02,
            SECTION_PROMPTS["script"]: 0.02,
            SECTION_PROMPTS["full"]: 0.02,
        },
    )
    svc = _make_service_with_provider(provider)

    gen = svc.stream_three_segments("Q?")

    # 拿前几个事件（足够触发各段 producer 启动）
    received = 0
    async for ev in gen:
        received += 1
        if received >= 4:
            break

    assert provider.start_count >= 1, "至少有一个 mock generator 启动了"

    # 主动 aclose → 触发 finally → 取消所有 task → sync_iter.close()
    await gen.aclose()

    # 给一点时间让所有 task finally 跑完
    await asyncio.sleep(0.1)

    # 注意：sync_iter.close() 触发 GeneratorExit 时 mock 计数 close_count
    # 但 ask_stream 抛错 / generator 已耗尽时不会进 GeneratorExit 分支
    # 此处至少有 >=1 段还没跑完 → close_count >= 1
    assert provider.close_count >= 1, (
        f"aclose 后应至少有 1 个 sync generator 被 close, "
        f"实际 close_count={provider.close_count}, "
        f"start_count={provider.start_count}"
    )


# ---------------- 5. 配置：默认 provider 路由 ----------------

def test_init_picks_default_provider(monkeypatch):
    """configs 里多 provider，按 default 选并实例化。"""

    instantiated: dict = {}

    class _FakeProvider:
        def __init__(self, cfg):
            instantiated["cfg"] = cfg

        def ask(self, *a, **kw):  # pragma: no cover
            return ""

    # 替换 registry 里的 deepseek
    from app.llm import service as svc_mod

    monkeypatch.setitem(
        svc_mod._PROVIDER_REGISTRY, "deepseek", _FakeProvider
    )

    cfg = {
        "providers": [
            {
                "name": "claude",
                "api_key": "sk-claude",
                "model": "claude-sonnet",
            },
            {
                "name": "deepseek",
                "api_key": "sk-ds",
                "model": "deepseek-chat",
            },
        ],
        "default": "deepseek",
    }
    svc = LLMService(cfg)

    assert svc.provider_name == "deepseek"
    assert isinstance(svc.provider, _FakeProvider)
    assert instantiated["cfg"] == {
        "api_key": "sk-ds",
        "model": "deepseek-chat",
    }


# ---------------- 6. 配置：default 不存在 → RuntimeError ----------------

def test_init_raises_if_default_missing():
    cfg = {
        "providers": [
            {
                "name": "claude",
                "api_key": "sk-c",
                "model": "claude-sonnet",
            }
        ],
        "default": "deepseek",  # 不在 providers 里
    }
    with pytest.raises(RuntimeError, match="not configured"):
        LLMService(cfg)


def test_init_raises_if_default_empty():
    """default 字段缺失 / 空也要明确报错。"""
    with pytest.raises(RuntimeError, match="default provider"):
        LLMService({"providers": []})


def test_init_raises_if_provider_unknown(monkeypatch):
    """default 在 providers 列表里但不是已知类型也要报错。"""
    cfg = {
        "providers": [
            {
                "name": "myllm",
                "api_key": "x",
                "model": "y",
            }
        ],
        "default": "myllm",
    }
    with pytest.raises(RuntimeError, match="Unknown LLM provider"):
        LLMService(cfg)
