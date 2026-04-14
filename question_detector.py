import time

QUESTION_MARKS = ("?", "?")
QUESTION_WORDS = (
    "什么", "怎么", "为什么", "如何", "哪", "谁", "几",
    "是不是", "有没有", "能不能", "可不可以", "对不对",
    "说一下", "讲一下", "介绍一下", "聊聊", "谈谈",
    "请你", "请问", "你觉得", "你认为", "你会", "你能",
    "区别", "原理", "实现", "设计", "优化"
)


class QuestionDetector:
    """
    把转写文本缓冲起来,判断"一句话说完了"并且"这是个问题",然后输出。

    触发条件:
    1. buffer 末尾出现问号 → 立即输出
    2. 距离上一次喂入超过 silence_seconds,且 buffer 含有问题特征词 → 输出
    3. buffer 过长但不像问题 → 清空避免堆积
    """

    def __init__(self, silence_seconds=1.2, min_chars=6):
        self.silence_seconds = silence_seconds
        self.min_chars = min_chars
        self.buffer = ""
        self.last_update = time.time()

    def feed(self, text: str):
        text = (text or "").strip()
        if text:
            self.buffer += text
            self.last_update = time.time()

        if self.buffer.endswith(QUESTION_MARKS):
            return self._flush()

        if (time.time() - self.last_update) >= self.silence_seconds:
            if len(self.buffer) >= self.min_chars and self._looks_like_question(self.buffer):
                return self._flush()
            if len(self.buffer) >= 80:
                self.buffer = ""
        return None

    def _looks_like_question(self, s: str) -> bool:
        return any(w in s for w in QUESTION_WORDS) or s.endswith(QUESTION_MARKS)

    def _flush(self):
        q = self.buffer.strip()
        self.buffer = ""
        return q if len(q) >= self.min_chars else None
