from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox, QTabWidget
)
from PySide6.QtCore import Qt, Signal


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("设置")
        self.resize(540, 480)

        tabs = QTabWidget()

        # ===== ASR 标签页 =====
        asr_tab = QWidget()
        asr_layout = QFormLayout(asr_tab)

        self.asr_engine = QComboBox()
        self.asr_engine.addItems(["faster_whisper", "aliyun"])
        self.asr_engine.setCurrentText(config["asr"]["engine"])
        asr_layout.addRow("引擎", self.asr_engine)

        self.whisper_model = QLineEdit(config["asr"]["faster_whisper"]["model"])
        asr_layout.addRow("Whisper 模型", self.whisper_model)

        self.whisper_prompt = QLineEdit(config["asr"]["faster_whisper"]["initial_prompt"])
        asr_layout.addRow("Whisper 提示词", self.whisper_prompt)

        self.aliyun_appkey = QLineEdit(config["asr"]["aliyun"]["app_key"])
        self.aliyun_token = QLineEdit(config["asr"]["aliyun"]["token"])
        self.aliyun_token.setEchoMode(QLineEdit.Password)
        asr_layout.addRow("阿里云 AppKey", self.aliyun_appkey)
        asr_layout.addRow("阿里云 Token", self.aliyun_token)

        tabs.addTab(asr_tab, "语音识别")

        # ===== LLM 标签页 =====
        llm_tab = QWidget()
        llm_layout = QFormLayout(llm_tab)

        self.llm_provider = QComboBox()
        self.llm_provider.addItems(["claude", "openai", "grok", "gemini"])
        self.llm_provider.setCurrentText(config["llm"]["provider"])
        llm_layout.addRow("当前模型", self.llm_provider)

        self.key_inputs = {}
        self.model_inputs = {}
        for p in ["claude", "openai", "grok", "gemini"]:
            key = QLineEdit(config["llm"][p]["api_key"])
            model = QLineEdit(config["llm"][p]["model"])
            self.key_inputs[p] = key
            self.model_inputs[p] = model
            llm_layout.addRow(f"{p} API Key", key)
            llm_layout.addRow(f"{p} 模型名", model)

        tabs.addTab(llm_tab, "LLM")

        # ===== 音频标签页 =====
        audio_tab = QWidget()
        audio_layout = QFormLayout(audio_tab)
        self.audio_device = QLineEdit(config["audio"]["input_device_name"])
        audio_layout.addRow("输入设备名称", self.audio_device)
        audio_layout.addRow(QLabel("提示: Mac 下通常填 'BlackHole 2ch'"))
        tabs.addTab(audio_tab, "音频")

        main = QVBoxLayout(self)
        main.addWidget(tabs)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        main.addWidget(btns)

    def apply_to_config(self):
        self.config["asr"]["engine"] = self.asr_engine.currentText()
        self.config["asr"]["faster_whisper"]["model"] = self.whisper_model.text()
        self.config["asr"]["faster_whisper"]["initial_prompt"] = self.whisper_prompt.text()
        self.config["asr"]["aliyun"]["app_key"] = self.aliyun_appkey.text()
        self.config["asr"]["aliyun"]["token"] = self.aliyun_token.text()
        self.config["llm"]["provider"] = self.llm_provider.currentText()
        for p in ["claude", "openai", "grok", "gemini"]:
            self.config["llm"][p]["api_key"] = self.key_inputs[p].text()
            self.config["llm"][p]["model"] = self.model_inputs[p].text()
        self.config["audio"]["input_device_name"] = self.audio_device.text()
        return self.config


class FloatingWindow(QWidget):
    settings_changed = Signal()
    toggle_asr = Signal()

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._drag_pos = None

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(480, 580)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        container = QWidget()
        container.setStyleSheet("""
            QWidget {
                background-color: rgba(20, 20, 25, 220);
                border-radius: 12px;
                color: #e8e8e8;
            }
            QLabel#title { color: #9ab; font-weight: bold; font-size: 14px; }
            QLabel { color: #aab; font-size: 12px; }
            QTextEdit {
                background-color: rgba(0,0,0,80);
                border: 1px solid rgba(255,255,255,30);
                border-radius: 6px;
                padding: 6px;
                color: #e8e8e8;
                font-size: 13px;
            }
            QPushButton {
                background-color: rgba(100,140,200,180);
                border: none; border-radius: 6px;
                padding: 5px 10px; color: white;
                font-size: 12px;
            }
            QPushButton:hover { background-color: rgba(120,160,220,220); }
        """)
        cl = QVBoxLayout(container)

        # 顶栏
        top = QHBoxLayout()
        self.title = QLabel("面试助手")
        self.title.setObjectName("title")
        self.asr_btn = QPushButton(self._asr_label())
        self.asr_btn.clicked.connect(self.toggle_asr.emit)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedWidth(32)
        self.settings_btn.clicked.connect(self._open_settings)
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedWidth(32)
        self.close_btn.clicked.connect(self.close)

        top.addWidget(self.title)
        top.addStretch()
        top.addWidget(self.asr_btn)
        top.addWidget(self.settings_btn)
        top.addWidget(self.close_btn)
        cl.addLayout(top)

        cl.addWidget(QLabel("实时转写"))
        self.transcript_view = QTextEdit()
        self.transcript_view.setReadOnly(True)
        self.transcript_view.setFixedHeight(150)
        cl.addWidget(self.transcript_view)

        cl.addWidget(QLabel("AI 回答"))
        self.answer_view = QTextEdit()
        self.answer_view.setReadOnly(True)
        cl.addWidget(self.answer_view)

        root.addWidget(container)

    def _asr_label(self):
        names = {"faster_whisper": "Whisper本地", "aliyun": "阿里云"}
        return f"ASR: {names.get(self.config['asr']['engine'], '?')}"

    def refresh_asr_label(self):
        self.asr_btn.setText(self._asr_label())

    def append_transcript(self, text):
        self.transcript_view.append(text)
        sb = self.transcript_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_answer(self, text):
        self.answer_view.setPlainText(text)

    def set_status(self, text):
        self.title.setText(f"面试助手 · {text}")

    def _open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            self.config = dlg.apply_to_config()
            self.refresh_asr_label()
            self.settings_changed.emit()

    # 窗口拖动
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
