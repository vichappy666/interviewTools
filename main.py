import sys
import threading
import traceback

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, QTimer

from config import load_config, save_config
from audio_capture import AudioCapture
from asr import build_asr
from llm import build_llm
from question_detector import QuestionDetector
from ui import FloatingWindow


class Worker(QObject):
    transcript_ready = Signal(str)
    question_ready = Signal(str)
    answer_ready = Signal(str)
    status = Signal(str)
    error = Signal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = False
        self.audio = None
        self.asr = None
        self.llm = None
        self.detector = None
        self.thread = None

    def update_config(self, config):
        self.config = config

    def start(self):
        try:
            self.status.emit("初始化...")
            self.audio = AudioCapture(
                self.config["audio"]["input_device_name"],
                self.config["audio"]["sample_rate"],
                self.config["audio"]["chunk_seconds"]
            )
            self.asr = build_asr(self.config)
            # self.llm = build_llm(self.config)
            self.detector = QuestionDetector(
                self.config["question_detection"]["silence_seconds"],
                self.config["question_detection"]["min_chars"]
            )
            self.audio.start()
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
            self.status.emit("监听中")
        except Exception as e:
            traceback.print_exc()
            self.error.emit(f"启动失败: {e}")

    def stop(self):
        self.running = False
        if self.audio:
            self.audio.stop()
            self.audio = None

    def _loop(self):
        sr = self.config["audio"]["sample_rate"]
        while self.running:
            chunk = self.audio.read_chunk(timeout=1.0) if self.audio else None
            if chunk is None:
                q = self.detector.feed("") if self.detector else None
                if q:
                    self._handle_question(q)
                continue
            try:
                text = self.asr.transcribe(chunk, sr)
            except Exception as e:
                self.error.emit(f"ASR 错误: {e}")
                continue
            if text:
                self.transcript_ready.emit(text)
                q = self.detector.feed(text)
                if q:
                    self._handle_question(q)

    def _handle_question(self, question):
        self.question_ready.emit(question)
        # LLM 暂时跳过，只测试语音转文字
        self.status.emit("监听中")


def main():
    app = QApplication(sys.argv)
    config = load_config()
    window = FloatingWindow(config)
    window.show()

    worker = Worker(config)

    worker.transcript_ready.connect(window.append_transcript)
    worker.question_ready.connect(
        lambda q: window.append_transcript(f"\n🎯 识别到问题: {q}\n")
    )
    worker.answer_ready.connect(window.set_answer)
    worker.status.connect(window.set_status)
    worker.error.connect(lambda msg: window.set_status(f"错误: {msg}"))

    def restart_worker():
        save_config(window.config)
        worker.update_config(window.config)
        worker.stop()
        QTimer.singleShot(600, worker.start)

    def toggle_asr():
        cur = window.config["asr"]["engine"]
        window.config["asr"]["engine"] = "aliyun" if cur == "faster_whisper" else "faster_whisper"
        window.refresh_asr_label()
        restart_worker()

    window.settings_changed.connect(restart_worker)
    window.toggle_asr.connect(toggle_asr)

    worker.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
