from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox, QTabWidget,
    QGraphicsDropShadowEffect, QListWidget, QListWidgetItem, QTextBrowser,
    QSizePolicy, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QColor, QTextCursor, QFont, QGuiApplication, QTextCharFormat


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


class TranscriptView(QTextEdit):
    """转写显示区：保留 partial 覆盖 / final 固定行为，新 partial 刷新不抢用户选区/光标。"""

    ask_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("等待语音输入...")
        self._partial_start = 0
        self._popup = SelectionPopup(self)
        self._popup.ask_requested.connect(self._emit_ask_from_selection)
        self.selectionChanged.connect(self._on_selection_changed)

    def update_partial(self, text: str):
        """覆盖当前 partial 行，不动用户的 textCursor。"""
        doc = self.document()
        edit_cursor = QTextCursor(doc)
        edit_cursor.setPosition(self._partial_start)
        edit_cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        edit_cursor.insertText(text)
        self._autoscroll_if_appropriate()

    def commit_final(self, text: str):
        """把当前行固定（加换行），下一轮 partial 从新行开始。"""
        doc = self.document()
        edit_cursor = QTextCursor(doc)
        edit_cursor.setPosition(self._partial_start)
        edit_cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        edit_cursor.insertText(text + "\n")
        self._partial_start = edit_cursor.position()
        self._autoscroll_if_appropriate()

    def _autoscroll_if_appropriate(self):
        """只有用户没选中 且 滚动条贴底时才自动滚到底。"""
        if self.textCursor().hasSelection():
            return
        sb = self.verticalScrollBar()
        if sb.maximum() - sb.value() > 40:
            return
        sb.setValue(sb.maximum())

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() != Qt.LeftButton:
            return
        self._maybe_show_popup()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self._popup.isVisible():
            self._popup.hide()
            return
        super().keyPressEvent(e)

    def _on_selection_changed(self):
        if not self.textCursor().hasSelection():
            self._popup.hide()

    def _maybe_show_popup(self):
        cursor = self.textCursor()
        text = cursor.selectedText().strip()
        if len(text) < 2:
            self._popup.hide()
            return
        rect = self.cursorRect(cursor)
        viewport = self.viewport()
        top_right_local = rect.topRight()
        global_pos = viewport.mapToGlobal(top_right_local)
        global_pos.setX(global_pos.x() + 8)
        global_pos.setY(global_pos.y() - 36)
        screen = self.screen().availableGeometry()
        popup_w = 120
        popup_h = 36
        if global_pos.x() + popup_w > screen.right():
            global_pos.setX(screen.right() - popup_w - 4)
        if global_pos.y() < screen.top():
            bottom_left = viewport.mapToGlobal(rect.bottomLeft())
            bottom_left.setY(bottom_left.y() + 8)
            global_pos = bottom_left
        self._popup.show_at(global_pos, text)

    def _emit_ask_from_selection(self, text: str):
        self.ask_requested.emit(text)


class AnswerView(QWidget):
    """AI 回答区：三段面板（要点 / 话术 / 完整答案）+ 问题头。"""

    SECTION_ORDER = [
        ("key_points", "要点"),
        ("script", "话术"),
        ("full", "完整答案"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        self.q_label = QLabel("")
        self.q_label.setWordWrap(True)
        self.q_label.setStyleSheet(
            "color: #7eb8f0; font-weight: bold; font-size: 13px; margin-bottom: 4px;"
        )

        self._panels = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.q_label)

        for name, title in self.SECTION_ORDER:
            p = _SectionPanel(name, title)
            self._panels[name] = p
            lay.addWidget(p)

        self._placeholder = QLabel("点击右侧问题或在转写区划选文字后发问...")
        self._placeholder.setStyleSheet("color: #556677;")
        lay.addWidget(self._placeholder)
        lay.addStretch()

        self._set_content_visible(False)

    def begin_answer(self, question: str):
        self._set_content_visible(True)
        q = question.strip()
        if len(q) > 80:
            q = q[:80] + "…"
        self.q_label.setText(f"Q：{q}")
        for p in self._panels.values():
            p.reset()

    def on_section_start(self, name: str):
        if name in self._panels:
            self._panels[name].mark_start()

    def on_section_chunk(self, name: str, text: str):
        if name in self._panels:
            self._panels[name].append_chunk(text)

    def on_section_end(self, name: str):
        if name in self._panels:
            self._panels[name].mark_end()

    def on_non_question(self):
        self.q_label.setText("[非问题 · 跳过]")
        for p in self._panels.values():
            p.reset()

    def _set_content_visible(self, visible: bool):
        self._placeholder.setVisible(not visible)
        self.q_label.setVisible(visible)
        for p in self._panels.values():
            p.setVisible(visible)


class QuestionListView(QTextBrowser):
    """识别到的问题队列。每条占一个 block（段落）。支持：
    - 点击一条 → 发问整条
    - 划选文字（可跨条）→ 弹气泡，点 [问 AI] 发问选中文本
    - Esc 或取消选中 → 关气泡
    已问的条目变灰。
    """

    ask_requested = Signal(str)

    STATE_PENDING = "pending"
    STATE_ASKED = "asked"

    COLOR_PENDING = QColor("#e0e8f0")
    COLOR_ASKED = QColor("#7a8899")

    MAX_ITEMS = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet("""
            QTextBrowser {
                background-color: rgba(0, 0, 0, 60);
                border: 1px solid rgba(100, 140, 200, 25);
                border-radius: 10px;
                padding: 8px;
                color: #e0e8f0;
                font-size: 12px;
            }
        """)

        # _rows 和 document 的 block 一一对应（按追加顺序）
        # 每项：{"text": 原始文本, "state": pending/asked}
        self._rows = []

        self._popup = SelectionPopup(self)
        self._popup.ask_requested.connect(self._on_popup_ask)

        self.selectionChanged.connect(self._on_selection_changed)

        self._user_scrolled_up = False
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    # ---------- 对外 ----------

    def add_question(self, text: str):
        text = (text or "").strip()
        if not text:
            return

        doc = self.document()
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.End)

        # 如果文档不为空，先起新 block
        if doc.blockCount() > 1 or doc.firstBlock().text():
            cursor.insertBlock()

        fmt = QTextCharFormat()
        fmt.setForeground(self.COLOR_PENDING)
        cursor.insertText(text, fmt)

        self._rows.append({"text": text, "state": self.STATE_PENDING})

        # LRU：超过 MAX_ITEMS 删最早的 block
        while len(self._rows) > self.MAX_ITEMS:
            self._remove_first_block()
            self._rows.pop(0)

        if not self._user_scrolled_up:
            sb = self.verticalScrollBar()
            sb.setValue(sb.maximum())

    # ---------- 交互 ----------

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() != Qt.LeftButton:
            return

        selected = self.textCursor().selectedText().strip()
        if len(selected) >= 2:
            self._show_popup(selected)
            return

        # 无选中 → 当作点击整条：用坐标定位 block
        pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
        click_cursor = self.cursorForPosition(pos)
        block_num = click_cursor.block().blockNumber()
        if 0 <= block_num < len(self._rows):
            row = self._rows[block_num]
            if row["state"] == self.STATE_PENDING:
                self._mark_asked(block_num)
            self.ask_requested.emit(row["text"])

    def mouseDoubleClickEvent(self, e):
        super().mouseDoubleClickEvent(e)
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
        click_cursor = self.cursorForPosition(pos)
        block_num = click_cursor.block().blockNumber()
        if 0 <= block_num < len(self._rows):
            row = self._rows[block_num]
            self._mark_asked(block_num)
            self.ask_requested.emit(row["text"])

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self._popup.isVisible():
            self._popup.hide()
            return
        super().keyPressEvent(e)

    # ---------- 气泡 ----------

    def _on_selection_changed(self):
        if not self.textCursor().hasSelection():
            self._popup.hide()

    def _show_popup(self, selection_text: str):
        cursor = self.textCursor()
        rect = self.cursorRect(cursor)
        viewport = self.viewport()
        top_right_local = rect.topRight()
        global_pos = viewport.mapToGlobal(top_right_local)
        global_pos.setX(global_pos.x() + 8)
        global_pos.setY(global_pos.y() - 36)
        screen = self.screen().availableGeometry()
        popup_w = 120
        if global_pos.x() + popup_w > screen.right():
            global_pos.setX(screen.right() - popup_w - 4)
        if global_pos.y() < screen.top():
            bottom_left = viewport.mapToGlobal(rect.bottomLeft())
            bottom_left.setY(bottom_left.y() + 8)
            global_pos = bottom_left
        self._popup.show_at(global_pos, selection_text)

    def _on_popup_ask(self, text: str):
        self.ask_requested.emit(text)

    # ---------- 状态 ----------

    def _mark_asked(self, block_num: int):
        self._rows[block_num]["state"] = self.STATE_ASKED
        self._recolor_block(block_num, self.COLOR_ASKED)

    def _recolor_block(self, block_num: int, color: QColor):
        doc = self.document()
        block = doc.findBlockByNumber(block_num)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.StartOfBlock)
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        cursor.mergeCharFormat(fmt)

    def _remove_first_block(self):
        """从 document 开头删一个 block（含其后的换行）。"""
        doc = self.document()
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.Start)
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        # 删掉跟随的换行（让下一个 block 上位）
        if not cursor.atEnd():
            cursor.deleteChar()

    def _on_scroll(self, value: int):
        sb = self.verticalScrollBar()
        self._user_scrolled_up = (sb.maximum() - value) > 20


class _SectionPanel(QWidget):
    """AnswerView 的单段：标题行 + 正文（QTextBrowser），支持流式 append。"""

    def __init__(self, name: str, display_title: str, parent=None):
        super().__init__(parent)
        self._name = name
        self._raw_text = ""
        self._state = "idle"

        title = QLabel(display_title)
        title.setStyleSheet("color: #7eb8f0; font-weight: bold; font-size: 13px;")

        self.copy_btn = QPushButton("📋 复制")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._on_copy)
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,15);
                color: #99a8b8; border: none; border-radius: 5px;
                padding: 3px 10px; font-size: 11px;
            }
            QPushButton:hover { background: rgba(255,255,255,30); color: #e0e8f0; }
        """)

        self.status_label = QLabel("· 等待中")
        self.status_label.setStyleSheet("color: #556677; font-size: 11px;")

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.copy_btn)
        head.addWidget(self.status_label)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        self.body.setMinimumHeight(60)
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.document().documentLayout().documentSizeChanged.connect(self._resize_to_content)
        self.body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.body.setStyleSheet("""
            QTextBrowser {
                background: rgba(0,0,0,30);
                border: 1px solid rgba(100,140,200,20);
                border-radius: 8px;
                padding: 8px;
                color: #e0e8f0;
                font-size: 13px;
            }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(4)
        lay.addLayout(head)
        lay.addWidget(self.body)

    def reset(self):
        self._raw_text = ""
        self._state = "idle"
        self.body.clear()
        self._resize_to_content()
        self.status_label.setText("· 等待中")
        self.status_label.setStyleSheet("color: #556677; font-size: 11px;")
        self.copy_btn.setText("📋 复制")

    def mark_start(self):
        self._state = "streaming"
        self.status_label.setText("⏳ 生成中")
        self.status_label.setStyleSheet("color: #fbbf24; font-size: 11px;")

    def append_chunk(self, text: str):
        self._raw_text += text
        self.body.setHtml(self._render_html(self._raw_text))
        sb = self.body.verticalScrollBar()
        sb.setValue(sb.maximum())

    def mark_end(self):
        self._state = "done"
        self.status_label.setText("✓ 已完成")
        self.status_label.setStyleSheet("color: #4ade80; font-size: 11px;")

    def plain_text(self) -> str:
        """去 Markdown `**` 的纯文本。"""
        return self._raw_text.replace("**", "").strip()

    def _on_copy(self):
        QGuiApplication.clipboard().setText(self.plain_text())
        self.copy_btn.setText("已复制 ✓")
        QTimer.singleShot(2000, lambda: self.copy_btn.setText("📋 复制"))

    @staticmethod
    def _render_html(md: str) -> str:
        """极简 Markdown → HTML：**粗体** + `- ` bullet。"""
        out = []
        in_ul = False
        for raw in md.split("\n"):
            line = raw.rstrip()
            if line.startswith("- "):
                if not in_ul:
                    out.append("<ul style='margin:4px 0; padding-left:20px'>")
                    in_ul = True
                body = _SectionPanel._render_inline(line[2:])
                out.append(f"<li>{body}</li>")
            else:
                if in_ul:
                    out.append("</ul>")
                    in_ul = False
                if line.strip():
                    body = _SectionPanel._render_inline(line)
                    out.append(f"<div>{body}</div>")
                else:
                    out.append("<div>&nbsp;</div>")
        if in_ul:
            out.append("</ul>")
        return "\n".join(out)

    @staticmethod
    def _render_inline(s: str) -> str:
        import re
        esc = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)

    def _resize_to_content(self, size=None):
        doc = self.body.document()
        # Make sure the document has a text width so it can compute a real height.
        # In some contexts (especially before the widget has been laid out), doc.size()
        # returns 0x0 until setTextWidth is called.
        vp_w = self.body.viewport().width()
        if vp_w > 0:
            doc.setTextWidth(vp_w)
        # document height + frame margins + a few px padding
        h = int(doc.size().height()) + 16
        self.body.setFixedHeight(max(60, h))


class SelectionPopup(QWidget):
    """选中文字后出现的浮动气泡：[🤖 问 AI] [×]。"""

    ask_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.ToolTip
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        container = QWidget(self)
        container.setObjectName("popup_container")
        container.setStyleSheet("""
            QWidget#popup_container {
                background-color: #1a1a2e;
                border: 1px solid rgba(126, 184, 240, 80);
                border-radius: 8px;
            }
            QPushButton#ask {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(70, 120, 200, 230),
                    stop:1 rgba(100, 150, 230, 230));
                color: white;
                border: none;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#ask:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(90, 140, 220, 240),
                    stop:1 rgba(120, 170, 250, 240));
            }
            QPushButton#close {
                background: rgba(255, 255, 255, 20);
                color: #99a8b8;
                border: none;
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton#close:hover {
                background: rgba(255, 255, 255, 40);
            }
        """)

        lay = QHBoxLayout(container)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        self.ask_btn = QPushButton("🤖 问 AI")
        self.ask_btn.setObjectName("ask")
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("close")
        lay.addWidget(self.ask_btn)
        lay.addWidget(self.close_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        self.ask_btn.clicked.connect(self._on_ask)
        self.close_btn.clicked.connect(self.hide)

        self._selection_text = ""

    def show_at(self, global_pos, selection_text: str):
        self._selection_text = selection_text
        self.adjustSize()
        self.move(global_pos)
        self.show()

    def _on_ask(self):
        text = self._selection_text
        self.hide()
        if text:
            self.ask_requested.emit(text)


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
    ask_requested = Signal(str)

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
        self.resize(920, 1040)

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

        # 上半区：转写（左） + 问题列表（右）
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        section1 = QLabel("实时转写")
        section1.setObjectName("section")
        self.transcript_view = TranscriptView()
        self.transcript_view.setFixedHeight(260)
        left_col.addWidget(section1)
        left_col.addWidget(self.transcript_view)

        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        section_q = QLabel("识别的问题  (点击发问)")
        section_q.setObjectName("section")
        self.question_list = QuestionListView()
        self.question_list.setFixedHeight(260)
        right_col.addWidget(section_q)
        right_col.addWidget(self.question_list)

        # 左 1.5 : 右 1
        top_row.addLayout(left_col, 3)
        top_row.addLayout(right_col, 2)
        cl.addLayout(top_row)

        # 回答区
        section2 = QLabel("AI 回答")
        section2.setObjectName("section")
        cl.addWidget(section2)

        self.answer_view = AnswerView()
        answer_scroll = QScrollArea()
        answer_scroll.setWidget(self.answer_view)
        answer_scroll.setWidgetResizable(True)
        answer_scroll.setFrameShape(QScrollArea.NoFrame)
        answer_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        cl.addWidget(answer_scroll, 1)  # stretch factor 1 so it fills remaining vertical space

        root.addWidget(container)

        # 问题列表 / 气泡 的发问都汇到 ask_requested
        self.question_list.ask_requested.connect(self.ask_requested)
        self.transcript_view.ask_requested.connect(self.ask_requested)

    def update_partial(self, text):
        self.transcript_view.update_partial(text)

    def commit_final(self, text):
        self.transcript_view.commit_final(text)

    def add_question(self, text: str):
        self.question_list.add_question(text)

    def begin_answer(self, question: str):
        self.answer_view.begin_answer(question)

    def on_section_start(self, name: str):
        self.answer_view.on_section_start(name)

    def on_section_chunk(self, name: str, text: str):
        self.answer_view.on_section_chunk(name, text)

    def on_section_end(self, name: str):
        self.answer_view.on_section_end(name)

    def on_non_question(self):
        self.answer_view.on_non_question()

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
