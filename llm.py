from abc import ABC, abstractmethod

SYSTEM_PROMPT = """你是一位资深软件工程师,正在参加技术面试。
我会给你面试官提出的问题。请你给出一个清晰、专业、结构化的回答。

要求:
1. 直接给答案,不要写"好的"、"这是一个好问题"这类废话
2. 如果是概念题:先一句话定义,再讲核心原理,最后可选举例
3. 如果是系统设计:按"需求 → 核心方案 → 关键点 → 权衡"结构
4. 如果是算法题:讲思路和复杂度,必要时给伪代码
5. 控制在 300 字以内,重点突出
6. 使用中文,技术术语保留英文
7. 如果输入不是一个面试问题(比如只是寒暄、过渡语),只回复"[非问题]"
"""


class LLMProvider(ABC):
    @abstractmethod
    def ask(self, question: str) -> str: ...


class ClaudeProvider(LLMProvider):
    def __init__(self, cfg):
        from anthropic import Anthropic
        if not cfg["api_key"]:
            raise RuntimeError("Claude API key 未配置")
        self.client = Anthropic(api_key=cfg["api_key"])
        self.model = cfg["model"]

    def ask(self, question):
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=600,
            system=SYSTEM_PROMPT,
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

    def ask(self, question):
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=600,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
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

    def ask(self, question):
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=600,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question}
            ]
        )
        return resp.choices[0].message.content.strip()


class GeminiProvider(LLMProvider):
    def __init__(self, cfg):
        import google.generativeai as genai
        if not cfg["api_key"]:
            raise RuntimeError("Gemini API key 未配置")
        genai.configure(api_key=cfg["api_key"])
        self.model = genai.GenerativeModel(
            cfg["model"],
            system_instruction=SYSTEM_PROMPT
        )

    def ask(self, question):
        resp = self.model.generate_content(question)
        return resp.text.strip()


def build_llm(config):
    provider = config["llm"]["provider"]
    cfg = config["llm"][provider]
    mapping = {
        "claude": ClaudeProvider,
        "openai": OpenAIProvider,
        "grok":   GrokProvider,
        "gemini": GeminiProvider
    }
    return mapping[provider](cfg)
