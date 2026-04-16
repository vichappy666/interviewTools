from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox, QTabWidget,
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QTextCursor, QFont


STYLE_SHEET = """
QWidget#container {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(25, 25, 35, 235),
        stop:1 rgba(15, 15, 25, 245));
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 12);
}
QLabel#title {
    color: #7eb8f0;
    font-weight: bold;
    font-size: 15px;
    letter-spacing: 1px;
}
QLabel#section {
    color: #607088;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 2px;
    padding-top: 4px;
}
QLabel {
    color: #99a8b8;
    font-size: 12px;
}
QTextEdit {
    background-color: rgba(0, 0, 0, 60);
    border: 1px solid rgba(100, 140, 200, 25);
    border-radius: 10px;
    padding: 10px;
    color: #e0e8f0;
    font-size: 13px;
    font-family: "SF Mono", "Menlo", monospace;
    selection-background-color: rgba(100, 140, 200, 80);
}
QTextEdit:focus {
    border: 1px solid rgba(100, 140, 200, 60);
}
QPushButton#primary {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(70, 120, 200, 200),
        stop:1 rgba(100, 150, 230, 200));
    border: none;
    border-radius: 8px;
    padding: 6px 14px;
    color: white;
    font-size: 12px;
    font-weight: bold;
}
QPushButton#primary:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(90, 140, 220, 230),
        stop:1 rgba(120, 170, 250, 230));
}
QPushButton#icon {
    background-color: rgba(255, 255, 255, 8);
    border: 1px solid rgba(255, 255, 255, 15);
    border-radius: 8px;
    padding: 4px 8px;
    color: #8899aa;
    font-size: 14px;
}
QPushButton#icon:hover {
    background-color: rgba(255, 255, 255, 18);
    color: #aabbcc;
}
QLabel#status_dot {
    color: #4ade80;
    font-size: 8px;
}
"""

SETTINGS_STYLE = """
QDialog {
    background-color: #1a1a2e;
    color: #e0e8f0;
}
QTabWidget::pane {
    border: 1px solid rgba(100, 140, 200, 30);
    border-radius: 8px;
    background-color: rgba(0, 0, 0, 30);
}
QTabBar::tab {
    background-color: rgba(255, 255, 255, 5);
    color: #8899aa;
    padding: 8px 20px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: rgba(70, 120, 200, 40);
    color: #7eb8f0;
}
QLineEdit {
    background-color: rgba(0, 0, 0, 40);
    border: 1px solid rgba(100, 140, 200, 25);
    border-radius: 6px;
    padding: 6px 10px;
    color: #e0e8f0;
    font-size: 13px;
}
QLineEdit:focus {
    border: 1px solid rgba(100, 140, 200, 80);
}
QComboBox {
    background-color: rgba(0, 0, 0, 40);
    border: 1px solid rgba(100, 140, 200, 25);
    border-radius: 6px;
    padding: 6px 10px;
    color: #e0e8f0;
}
QComboBox::drop-down {
    border: none;
}
QComboBox QAbstractItemView {
    background-color: #1a1a2e;
    color: #e0e8f0;
    selection-background-color: rgba(70, 120, 200, 60);
}
QFormLayout {
    margin: 12px;
}
QLabel {
    color: #99a8b8;
    font-size: 12px;
}
QDialogButtonBox QPushButton {
    background-color: rgba(70, 120, 200, 180);
    border: none;
    border-radius: 6px;
    padding: 8px 24px;
    color: white;
    font-weight: bold;
}
QDialogButtonBox QPushButton:hover {
    background-color: rgba(90, 140, 220, 220);
}
"""


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("设置")
        self.setStyleSheet(SETTINGS_STYLE)
        self.resize(500, 400)

        tabs = QTabWidget()

        # ===== ASR 标签页 =====
        asr_tab = QWidget()
        asr_layout = QFormLayout(asr_tab)
        asr_layout.setSpacing(12)

        self.volc_appkey = QLineEdit(config["asr"]["volcengine"]["app_key"])
        self.volc_access_key = QLineEdit(config["asr"]["volcengine"]["access_key"])
        asr_layout.addRow("App Key", self.volc_appkey)
        asr_layout.addRow("Access Key", self.volc_access_key)

        tabs.addTab(asr_tab, "语音识别")

        # ===== LLM 标签页 =====
        llm_tab = QWidget()
        llm_layout = QFormLayout(llm_tab)
        llm_layout.setSpacing(12)

        self.llm_provider = QComboBox()
        self.llm_provider.addItems(["claude", "openai", "grok", "gemini", "deepseek"])
        self.llm_provider.setCurrentText(config["llm"]["provider"])
        llm_layout.addRow("当前模型", self.llm_provider)

        self.key_inputs = {}
        self.model_inputs = {}
        for p in ["claude", "openai", "grok", "gemini", "deepseek"]:
            key = QLineEdit(config["llm"][p]["api_key"])
            model = QLineEdit(config["llm"][p]["model"])
            self.key_inputs[p] = key
            self.model_inputs[p] = model
            llm_layout.addRow(f"{p.capitalize()} API Key", key)
            llm_layout.addRow(f"{p.capitalize()} 模型", model)

        tabs.addTab(llm_tab, "LLM")

        # ===== 音频标签页 =====
        audio_tab = QWidget()
        audio_layout = QFormLayout(audio_tab)
        audio_layout.setSpacing(12)
        self.audio_device = QLineEdit(config["audio"]["input_device_name"])
        audio_layout.addRow("输入设备", self.audio_device)
        hint = QLabel("填设备名称关键词，如 'MacBook Pro麦克风'")
        hint.setStyleSheet("color: #556677; font-size: 11px;")
        audio_layout.addRow("", hint)
        tabs.addTab(audio_tab, "音频")

        main = QVBoxLayout(self)
        main.setContentsMargins(16, 16, 16, 16)
        main.addWidget(tabs)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        main.addWidget(btns)

    def apply_to_config(self):
        self.config["asr"]["volcengine"]["app_key"] = self.volc_appkey.text()
        self.config["asr"]["volcengine"]["access_key"] = self.volc_access_key.text()
        self.config["llm"]["provider"] = self.llm_provider.currentText()
        for p in ["claude", "openai", "grok", "gemini", "deepseek"]:
            self.config["llm"][p]["api_key"] = self.key_inputs[p].text()
            self.config["llm"][p]["model"] = self.model_inputs[p].text()
        self.config["audio"]["input_device_name"] = self.audio_device.text()
        return self.config


class FloatingWindow(QWidget):
    settings_changed = Signal()

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
        self.resize(500, 600)

        self.setStyleSheet(STYLE_SHEET)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)

        container = QWidget()
        container.setObjectName("container")

        # 阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 120))
        container.setGraphicsEffect(shadow)

        cl = QVBoxLayout(container)
        cl.setContentsMargins(18, 14, 18, 14)
        cl.setSpacing(10)

        # 顶栏
        top = QHBoxLayout()
        top.setSpacing(8)

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("status_dot")
        self.status_dot.setFixedWidth(12)

        self.title = QLabel("面试助手")
        self.title.setObjectName("title")

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("icon")
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.clicked.connect(self._open_settings)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("icon")
        self.close_btn.setFixedSize(32, 32)
        self.close_btn.clicked.connect(self.close)

        top.addWidget(self.status_dot)
        top.addWidget(self.title)
        top.addStretch()
        top.addWidget(self.settings_btn)
        top.addWidget(self.close_btn)
        cl.addLayout(top)

        # 转写区
        section1 = QLabel("实时转写")
        section1.setObjectName("section")
        cl.addWidget(section1)

        self.transcript_view = QTextEdit()
        self.transcript_view.setReadOnly(True)
        self.transcript_view.setFixedHeight(180)
        self.transcript_view.setPlaceholderText("等待语音输入...")
        cl.addWidget(self.transcript_view)

        # 回答区
        section2 = QLabel("AI 回答")
        section2.setObjectName("section")
        cl.addWidget(section2)

        self.answer_view = QTextEdit()
        self.answer_view.setReadOnly(True)
        self.answer_view.setPlaceholderText("检测到问题后自动回答...")
        cl.addWidget(self.answer_view)

        root.addWidget(container)

        # 当前 partial 行的起始位置
        self._partial_start = 0

    def update_partial(self, text):
        """覆盖当前行显示 partial result"""
        cursor = self.transcript_view.textCursor()
        cursor.setPosition(self._partial_start)
        cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cursor.insertText(text)
        self.transcript_view.setTextCursor(cursor)
        sb = self.transcript_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def commit_final(self, text):
        """固定当前行，开始新行"""
        cursor = self.transcript_view.textCursor()
        cursor.setPosition(self._partial_start)
        cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cursor.insertText(text + "\n")
        self._partial_start = cursor.position()
        self.transcript_view.setTextCursor(cursor)
        sb = self.transcript_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_answer(self, text):
        self.answer_view.setPlainText(text)

    def set_status(self, text):
        self.title.setText(f"面试助手 · {text}")
        if "错误" in text:
            self.status_dot.setStyleSheet("color: #f87171; font-size: 8px;")
        elif "思考" in text:
            self.status_dot.setStyleSheet("color: #fbbf24; font-size: 8px;")
        else:
            self.status_dot.setStyleSheet("color: #4ade80; font-size: 8px;")

    def _open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            self.config = dlg.apply_to_config()
            self.settings_changed.emit()

    # 窗口拖动
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
