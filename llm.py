import os
from abc import ABC, abstractmethod
from typing import Iterator

# DeepSeek 是国内服务，绕过系统代理直连
for _key in ("NO_PROXY", "no_proxy"):
    _existing = os.environ.get(_key, "")
    if "api.deepseek.com" not in _existing:
        os.environ[_key] = (_existing + ",api.deepseek.com").lstrip(",")

SYSTEM_PROMPT = """你是一位资深软件工程师,正在参加技术面试。
我会给你面试官提出的问题。请你给出一个清晰、专业、结构化的回答。

要求:
1. 直接给答案,不要写"好的"、"这是一个好问题"这类废话
2. 如果是概念题:先一句话定义,再讲核心原理,最后可选举例
3. 如果是系统设计:按"需求 → 核心方案 → 关键点 → 权衡"结构
4. 如果是算法题:讲思路和复杂度,必要时给伪代码
5. 控制在 300 字以内,重点突出
6. 使用中文,技术术语保留英文
"""

SYSTEM_PROMPT_V2 = """你是一位资深软件工程师，正在参加技术面试。
我会给你面试官提出的问题。请你按以下三段 Markdown 格式回答，每段之间严格用 "## " 开头的标题分隔：

## 要点
用 3-9 条短 bullet 列出核心知识点，每条一行，不超过 15 字。每行以 "- " 开头。

## 话术
一段 2-4 句的自然口语化回答，像你要直接对面试官说出来的话。

## 完整答案
详细解释，可用 Markdown 加粗（**术语**）突出关键概念，可用 bullet 或段落。

硬性要求：
1. 三段标题必须原样一字不差："## 要点"、"## 话术"、"## 完整答案"
2. 顺序固定：要点 → 话术 → 完整答案
3. 每个标题前后各一个换行
4. 不要在三段之外添加任何其他文本（不要开场白、不要总结）
5. 使用中文，技术术语保留英文
"""

SECTION_PROMPTS = {
    "key_points": """你是一位资深软件工程师，正在回答技术面试问题。
请用 3-9 条短 bullet 列出该问题的核心知识点，每条一行，每行以 "- " 开头，不超过 15 字。

硬性要求：
1. 只输出 bullet 列表，不要标题、不要开场白、不要总结
2. 使用中文，技术术语保留英文
""",
    "script": """你是一位资深软件工程师，正在回答技术面试问题。
请用一段 2-4 句的自然口语化回答，像你要直接对面试官说出来的话。

硬性要求：
1. 只输出这段口语回答，不要标题、不要 bullet、不要开场白
2. 使用中文，技术术语保留英文
""",
    "full": """你是一位资深软件工程师，正在回答技术面试问题。
请详细解释这个问题，可用 Markdown 加粗（**术语**）突出关键概念，可用 bullet 或段落。

硬性要求：
1. 只输出详细解释内容，不要标题（不要写 "## 完整答案" 这种）、不要开场白、不要总结
2. 使用中文，技术术语保留英文
"""
}


class LLMProvider(ABC):
    @abstractmethod
    def ask(self, question: str, system_prompt: str = None) -> str: ...

    def ask_stream(self, question: str, system_prompt: str = None) -> Iterator[str]:
        """默认：一次性调 ask() 返回整个答案。

        注：generator 支持通过 .close() 提前中断；子类实现真流式时应保证
        GeneratorExit 时底层 HTTP 连接被关闭。
        """
        yield self.ask(question, system_prompt)


class ClaudeProvider(LLMProvider):
    def __init__(self, cfg):
        from anthropic import Anthropic
        if not cfg["api_key"]:
            raise RuntimeError("Claude API key 未配置")
        self.client = Anthropic(api_key=cfg["api_key"])
        self.model = cfg["model"]

    def ask(self, question, system_prompt=None):
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=system_prompt or SYSTEM_PROMPT_V2,
            messages=[{"role": "user", "content": question}]
        )
        return resp.content[0].text.strip()


class OpenAIProvider(LLMProvider):
    def __init__(self, cfg):
        from openai import OpenAI
        if not cfg["api_key"]:
            raise RuntimeError("OpenAI API key 未配置")
        self.client = OpenAI(api_key=cfg["api_key"])
        self.model = cfg["model"]

    def ask(self, question, system_prompt=None):
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": system_prompt or SYSTEM_PROMPT_V2},
                {"role": "user", "content": question}
            ]
        )
        return resp.choices[0].message.content.strip()


class GrokProvider(LLMProvider):
    def __init__(self, cfg):
        from openai import OpenAI
        if not cfg["api_key"]:
            raise RuntimeError("Grok API key 未配置")
        self.client = OpenAI(
            api_key=cfg["api_key"],
            base_url="https://api.x.ai/v1"
        )
        self.model = cfg["model"]

    def ask(self, question, system_prompt=None):
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": system_prompt or SYSTEM_PROMPT_V2},
                {"role": "user", "content": question}
            ]
        )
        return resp.choices[0].message.content.strip()


class DeepSeekProvider(LLMProvider):
    def __init__(self, cfg):
        from openai import OpenAI
        if not cfg["api_key"]:
            raise RuntimeError("DeepSeek API key 未配置")
        self.client = OpenAI(
            api_key=cfg["api_key"],
            base_url="https://api.deepseek.com"
        )
        self.model = cfg["model"]

    def ask(self, question, system_prompt=None):
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": system_prompt or SYSTEM_PROMPT_V2},
                {"role": "user", "content": question}
            ]
        )
        return resp.choices[0].message.content.strip()

    def ask_stream(self, question, system_prompt=None):
        stream = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2000,
            stream=True,
            messages=[
                {"role": "system", "content": system_prompt or SYSTEM_PROMPT_V2},
                {"role": "user", "content": question}
            ]
        )
        try:
            for chunk in stream:
                delta = getattr(chunk.choices[0].delta, "content", "") or ""
                if delta:
                    yield delta
        finally:
            try:
                stream.close()
            except Exception:
                pass


class GeminiProvider(LLMProvider):
    def __init__(self, cfg):
        import google.generativeai as genai
        if not cfg["api_key"]:
            raise RuntimeError("Gemini API key 未配置")
        genai.configure(api_key=cfg["api_key"])
        self._genai = genai
        self._model_name = cfg["model"]

    def _make_model(self, system_prompt=None):
        return self._genai.GenerativeModel(
            self._model_name,
            system_instruction=system_prompt or SYSTEM_PROMPT_V2
        )

    def ask(self, question, system_prompt=None):
        model = self._make_model(system_prompt)
        resp = model.generate_content(question)
        return resp.text.strip()


def build_llm(config):
    provider = config["llm"]["provider"]
    cfg = config["llm"][provider]
    mapping = {
        "claude":   ClaudeProvider,
        "openai":   OpenAIProvider,
        "grok":     GrokProvider,
        "gemini":   GeminiProvider,
        "deepseek": DeepSeekProvider
    }
    return mapping[provider](cfg)
