import sys
import traceback

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, QTimer

from config import load_config, save_config
from audio_capture import AudioCapture
from asr import StreamingASR
from llm import build_llm
from question_detector import QuestionDetector
from ui import FloatingWindow


class Worker(QObject):
    partial_text = Signal(str)
    final_text = Signal(str)
    question_ready = Signal(str)
    answer_ready = Signal(str)
    status = Signal(str)
    error = Signal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.audio = None
        self.asr = None
        self.llm = None
        self.detector = None

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
        self.status.emit("思考中...")
        try:
            answer = self.llm.ask(question)
            if answer and answer.strip() != "[非问题]":
                self.answer_ready.emit(answer)
            self.status.emit("监听中")
        except Exception as e:
            self.error.emit(f"LLM 错误: {e}")
            self.status.emit("监听中")


def main():
    app = QApplication(sys.argv)
    config = load_config()
    window = FloatingWindow(config)
    window.show()

    worker = Worker(config)

    worker.partial_text.connect(window.update_partial)
    worker.final_text.connect(window.commit_final)
    worker.question_ready.connect(
        lambda q: window.commit_final(f"\n🎯 识别到问题: {q}\n")
    )
    worker.answer_ready.connect(window.set_answer)
    worker.status.connect(window.set_status)
    worker.error.connect(lambda msg: window.set_status(f"错误: {msg}"))

    def restart_worker():
        save_config(window.config)
        worker.update_config(window.config)
        worker.stop()
        QTimer.singleShot(600, worker.start)

    window.settings_changed.connect(restart_worker)

    worker.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
