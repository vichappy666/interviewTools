"""
流式文本状态机。

LLM 会按以下格式吐 Markdown：

    ## 要点
    - ...
    - ...

    ## 话术
    ...

    ## 完整答案
    ...

StreamParser 接收 chunk（可能把 header 截成两半），通过回调
on_section_start / on_section_chunk / on_section_end 把三段事件流派发给消费者。

"[非问题]" 的短答案会通过 on_non_question 一次性通知。
"""

from typing import Callable, Optional


class StreamParser:
    HEADERS = {
        "## 要点": "key_points",
        "## 话术": "script",
        "## 完整答案": "full",
    }
    NON_QUESTION_MARKER = "[非问题]"
    MAX_HEADER_LEN = 20  # 最长的 header "## 完整答案" 是 10 字符，预留一倍

    def __init__(
        self,
        *,
        on_section_start: Callable[[str], None],
        on_section_chunk: Callable[[str, str], None],
        on_section_end: Callable[[str], None],
        on_non_question: Callable[[], None],
    ):
        self._on_start = on_section_start
        self._on_chunk = on_section_chunk
        self._on_end = on_section_end
        self._on_non_q = on_non_question

        self._buffer = ""
        self._current: Optional[str] = None
        self._closed = False
        self._non_question = False
        self._first_check_done = False

    def feed(self, chunk: str) -> None:
        """增量喂入文本。可能触发 0 个或多个回调。"""
        if self._closed or self._non_question:
            return

        # 统一换行符
        chunk = chunk.replace("\r\n", "\n").replace("\r", "\n")
        self._buffer += chunk

        # 非问题快速判定（前 20 字符内出现 [非问题]）
        if not self._first_check_done:
            stripped = self._buffer.lstrip()
            if stripped.startswith(self.NON_QUESTION_MARKER):
                self._non_question = True
                self._first_check_done = True
                self._on_non_q()
                return
            if len(stripped) >= 10 or "\n" in stripped:
                # 已有足够信息，不是 [非问题]
                self._first_check_done = True

        # 循环扫描 header，直到 buffer 没有完整 header 可切
        while True:
            header_pos, header_key, header_len = self._find_next_header()
            if header_pos < 0:
                break  # 没有完整 header，跳出去等下一 chunk

            # header 之前的文本归当前 section
            before = self._buffer[:header_pos]
            if before and self._current is not None:
                self._on_chunk(self._current, before)

            # 结束当前 section（若有）
            if self._current is not None:
                self._on_end(self._current)

            # 切到新 section
            self._current = self.HEADERS[header_key]
            self._on_start(self._current)

            # buffer 往后推到 header 结束
            self._buffer = self._buffer[header_pos + header_len:]

        # 本轮没再找到 header。吐出"安全部分"给当前 section：
        # buffer 末尾最多保留 MAX_HEADER_LEN 字符不吐（可能是下一 header 的前缀）
        if self._current is not None and self._buffer:
            safe_len = max(0, len(self._buffer) - self.MAX_HEADER_LEN)
            if safe_len > 0:
                self._on_chunk(self._current, self._buffer[:safe_len])
                self._buffer = self._buffer[safe_len:]

    def close(self) -> None:
        """流结束时冲刷尾部 buffer，触发最后的 section_end。"""
        if self._closed or self._non_question:
            self._closed = True
            return
        if self._current is not None:
            if self._buffer:
                self._on_chunk(self._current, self._buffer)
                self._buffer = ""
            self._on_end(self._current)
            self._current = None
        self._closed = True

    def _find_next_header(self):
        """
        在 self._buffer 里找下一个完整 header（`## 要点` / `## 话术` / `## 完整答案`）。
        必须能确定 header 完整 —— 要求 header 要么在 buffer 开头，要么前面有 `\n`，且后面紧跟 `\n`。
        返回 (position_of_##, header_key, length_including_trailing_newline) 或 (-1, None, 0)。
        """
        best = (-1, None, 0)
        for key in self.HEADERS:
            start = 0
            while True:
                idx = self._buffer.find(key, start)
                if idx < 0:
                    break
                # 前置条件：开头 或 前一字符是 \n
                if idx != 0 and self._buffer[idx - 1] != "\n":
                    start = idx + 1
                    continue
                # 后置条件：key 之后必须跟 \n（确保 header 不是正文里的巧合）
                after = idx + len(key)
                if after >= len(self._buffer):
                    # buffer 还没包含 header 后的换行，等下一 chunk
                    start = idx + 1
                    continue
                if self._buffer[after] != "\n":
                    # 后面不是 \n（比如 `## 要点abc`），不是真 header
                    start = idx + 1
                    continue
                # 命中
                total_len = len(key) + 1  # 含尾部 \n
                if best[0] < 0 or idx < best[0]:
                    best = (idx, key, total_len)
                break  # 这个 key 已找到最早的，继续看其他 key
        return best
