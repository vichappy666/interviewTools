import sys
import threading
import time
import traceback

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, QTimer, Qt

from config import load_config, save_config
from audio_capture import AudioCapture
from asr import StreamingASR
from llm import build_llm
from question_detector import QuestionDetector
from ui import FloatingWindow
from web_server import WebBridge, get_lan_ip


class Worker(QObject):
    partial_text = Signal(str)
    final_text = Signal(str)
    question_ready = Signal(str)
    answer_started = Signal(str)          # question
    section_start = Signal(str)           # name
    section_chunk = Signal(str, str)      # name, text
    section_end = Signal(str)             # name
    status = Signal(str)
    error = Signal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.audio = None
        self.asr = None
        self.llm = None
        self.detector = None
        self._pending_token = 0

    def update_config(self, config):
        self.config = config

    def start(self):
        try:
            self.status.emit("初始化...")

            self.detector = QuestionDetector(
                self.config["question_detection"]["silence_seconds"],
                self.config["question_detection"]["min_chars"]
            )

            self.llm = build_llm(self.config)

            self.asr = StreamingASR(
                self.config["asr"]["volcengine"],
                on_partial=self._on_partial,
                on_final=self._on_final,
                on_error=self._on_error,
            )
            self.asr.start()

            self.audio = AudioCapture(
                self.config["audio"]["input_device_name"],
                self.config["audio"]["sample_rate"],
                on_audio=self.asr.feed,
            )
            self.audio.start()

            self.status.emit("监听中")
        except Exception as e:
            traceback.print_exc()
            self.error.emit(f"启动失败: {e}")

    def stop(self):
        if self.audio:
            self.audio.stop()
            self.audio = None
        if self.asr:
            self.asr.stop()
            self.asr = None

    def _on_partial(self, text):
        self.partial_text.emit(text)

    def _on_final(self, text):
        self.final_text.emit(text)
        if self.detector:
            q = self.detector.feed(text)
            if q:
                self._handle_question(q)

    def _on_error(self, msg):
        self.error.emit(msg)

    def _handle_question(self, question):
        self.question_ready.emit(question)

    def ask(self, question: str):
        """用户手动发问：取消上一次未完成的请求，并行起 3 个线程各拉一段流。"""
        if not question or not question.strip():
            return
        self._pending_token += 1
        token = self._pending_token
        provider = self.config["llm"]["provider"]
        q_preview = question.strip().replace("\n", " ")[:60]
        print(f"[llm] ask token={token} provider={provider} q='{q_preview}'")
        self.status.emit("思考中...")
        threading.Thread(
            target=self._dispatch_parallel_stream,
            args=(question.strip(), token),
            daemon=True,
        ).start()

    def _dispatch_parallel_stream(self, question: str, token: int):
        """主调度：发 answer_started，起 3 个子线程各拉一段。"""
        if token != self._pending_token:
            return
        self.answer_started.emit(question)

        threads = []
        for section in ("key_points", "script", "full"):
            t = threading.Thread(
                target=self._run_section_stream,
                args=(question, section, token),
                daemon=True,
            )
            t.start()
            threads.append(t)

        # 等三段都结束再改 status
        for t in threads:
            t.join()
        # 过期 token 不动 status
        if token == self._pending_token:
            self.status.emit("监听中")

    def _run_section_stream(self, question: str, section_name: str, token: int):
        """单段：向 LLM 拉这段的流，边拉边 emit section_chunk。"""
        from llm import SECTION_PROMPTS

        if token != self._pending_token:
            return

        self.section_start.emit(section_name)
        prompt = SECTION_PROMPTS[section_name]
        provider = self.config["llm"]["provider"]
        t0 = time.time()
        first_logged = False
        n_chunks = 0

        stream_gen = self.llm.ask_stream(question, system_prompt=prompt)
        try:
            for chunk in stream_gen:
                if token != self._pending_token:
                    return
                if not first_logged:
                    first_logged = True
                    ms = int((time.time() - t0) * 1000)
                    print(f"[llm] {provider} {section_name} ✓ connected, first chunk in {ms}ms")
                n_chunks += 1
                if token == self._pending_token:
                    self.section_chunk.emit(section_name, chunk)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"[llm] {provider} {section_name} ✗ error after {elapsed:.1f}s: {e}")
            if token == self._pending_token:
                self.error.emit(f"LLM 错误 ({section_name}): {e}")
            return
        finally:
            # 强制关掉生成器 → 触发底层 stream 的 finally → 关 HTTP 连接 → 服务端不再计费
            try:
                stream_gen.close()
            except Exception:
                pass

        elapsed = time.time() - t0
        print(f"[llm] {provider} {section_name} ✓ done in {elapsed:.1f}s, {n_chunks} chunks")
        if token == self._pending_token:
            self.section_end.emit(section_name)


def main():
    app = QApplication(sys.argv)
    config = load_config()
    window = FloatingWindow(config)
    window.show()

    worker = Worker(config)

    worker.partial_text.connect(window.update_partial)
    worker.final_text.connect(window.commit_final)
    worker.question_ready.connect(window.add_question)
    worker.answer_started.connect(window.begin_answer)
    worker.section_start.connect(window.on_section_start)
    worker.section_chunk.connect(window.on_section_chunk)
    worker.section_end.connect(window.on_section_end)
    worker.status.connect(window.set_status)
    worker.error.connect(lambda msg: window.set_status(f"错误: {msg}"))

    # 用户点击列表 or 气泡 → Worker.ask
    window.ask_requested.connect(worker.ask)

    # Web 镜像：同一批信号再喂一份给 bridge，浏览器端同步
    web_cfg = config.get("web", {})
    bridge = None
    if web_cfg.get("enabled", True):
        bridge = WebBridge(
            host=web_cfg.get("host", "127.0.0.1"),
            port=int(web_cfg.get("port", 8765)),
        )
        worker.partial_text.connect(bridge.on_partial)
        worker.final_text.connect(bridge.on_final)
        worker.question_ready.connect(bridge.on_question_ready)
        worker.answer_started.connect(bridge.on_answer_started)
        worker.section_start.connect(bridge.on_section_start)
        worker.section_chunk.connect(bridge.on_section_chunk)
        worker.section_end.connect(bridge.on_section_end)
        worker.status.connect(bridge.on_status)
        worker.error.connect(bridge.on_error)
        # 浏览器发问 → worker（跨线程走 QueuedConnection）
        bridge.ask_requested.connect(worker.ask, Qt.QueuedConnection)
        bridge.start()
        # Qt UI 的 🌐 按钮需要知道真实 URL。绑到 0.0.0.0 时额外算出一个局域网 URL 给手机用
        local_url = f"http://127.0.0.1:{bridge.port}"
        lan_url = None
        if bridge.host in ("0.0.0.0", "::"):
            lan_ip = get_lan_ip()
            if lan_ip:
                lan_url = f"http://{lan_ip}:{bridge.port}"
        window.set_web_url(local_url, lan_url)

    def restart_worker():
        save_config(window.config)
        worker.update_config(window.config)
        worker.stop()
        QTimer.singleShot(600, worker.start)

    window.settings_changed.connect(restart_worker)

    worker.start()
    try:
        sys.exit(app.exec())
    finally:
        if bridge:
            bridge.stop()


if __name__ == "__main__":
    main()
