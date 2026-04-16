QUESTION_MARKS = ("?", "？")
QUESTION_WORDS = (
    "什么", "怎么", "为什么", "如何", "哪", "谁", "几",
    "是不是", "有没有", "能不能", "可不可以", "对不对",
    "说一下", "讲一下", "介绍一下", "聊聊", "谈谈",
    "请你", "请问", "你觉得", "你认为", "你会", "你能",
    "区别", "原理", "实现", "设计", "优化"
)


class QuestionDetector:
    """
    每个 ASR 产出的完整句子独立判断是否是问题。
    ASR 已在上游按句末标点切成 final，这里不再做 buffer 累积。

    判定规则:
    1. 句末 ? / ？ → 直接判为问题
    2. 否则，含特征词（什么/怎么/原理 等）→ 判为问题
    3. 其他 → 不是问题（寒暄、陈述等）
    """

    def __init__(self, silence_seconds=1.2, min_chars=6):
        # silence_seconds 保留参数兼容旧配置，实际不再使用
        self.min_chars = min_chars

    def feed(self, text: str):
        """每句 ASR final 喂一次。是问题就返回去掉首尾空白的文本，否则返回 None。"""
        text = (text or "").strip()
        if len(text) < self.min_chars:
            return None
        if self._looks_like_question(text):
            return text
        return None

    def _looks_like_question(self, s: str) -> bool:
        if s.endswith(QUESTION_MARKS):
            return True
        return any(w in s for w in QUESTION_WORDS)
