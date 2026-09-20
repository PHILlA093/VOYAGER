"""Voyager 1 主题:简洁科技风,白/灰主体,蓝/金点缀。"""

QSS = """
* {
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    color: #2b333d;
    font-size: 14px;
}
QMainWindow {
    background-color: #f4f6f9;
}
QDialog {
    background-color: #fafbfc;
}

/* ---------- 头部 ---------- */
#header {
    background-color: #ffffff;
    border-bottom: 1px solid #e2e6ec;
}
#titleGlyph {
    color: #c9a227;
    font-size: 16px;
    font-weight: bold;
}
#titleLabel {
    font-family: "Segoe UI", "Microsoft YaHei";
    font-size: 20px;
    font-weight: bold;
    color: #1e3a6e;
    letter-spacing: 1px;
}
#subtitleLabel {
    color: #8a94a6;
    font-size: 12px;
}
#statusDot {
    color: #c9a227;
    font-size: 12px;
}
#statusLabel {
    color: #8a94a6;
    font-size: 12px;
}

/* ---------- 侧边栏 ---------- */
#sidebar {
    background-color: #ffffff;
    border: none;
    border-right: 1px solid #e2e6ec;
    outline: 0;
    font-size: 14px;
}
#sidebar::item {
    color: #4a5568;
    padding: 12px 18px;
    border-left: 3px solid transparent;
}
#sidebar::item:selected {
    background-color: #eef4fe;
    color: #1e6fff;
    border-left: 3px solid #1e6fff;
    font-weight: bold;
}
#sidebar::item:hover {
    background-color: #f4f7fb;
}

/* ---------- 设置按钮 ---------- */
#settingsBtn, #memoryBtn, #ruminateBtn {
    background-color: #f0f3f7;
    color: #2b333d;
    border: 1px solid #dfe4ea;
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 13px;
}
#settingsBtn:hover, #memoryBtn:hover, #ruminateBtn:hover {
    background-color: #e4ecfb;
    border-color: #b9d0f5;
    color: #1e6fff;
}
#ruminateBtn {
    border-left: 3px solid #c9a227;
}

/* ---------- 聊天区(透明,露出太阳系背景) ---------- */
#chatScroll {
    background-color: transparent;
    border: none;
}
#chatArea {
    background-color: transparent;
}
QFrame#bubbleUser {
    background-color: #1e6fff;
    border-radius: 10px;
    border: none;
}
QFrame#bubbleAI {
    background-color: #ffffff;
    border-radius: 10px;
    border: 1px solid #e2e6ec;
    border-left: 3px solid #c9a227;
}
QLabel#bubbleUserLabel {
    color: #ffffff;
    font-size: 14px;
}
QLabel#bubbleAILabel {
    color: #2b333d;
    font-size: 14px;
}
QLabel#bubbleTime {
    color: #aab2bf;
    font-size: 11px;
}

/* ---------- 输入区 ---------- */
#inputPanel {
    background-color: #ffffff;
    border-top: 1px solid #e2e6ec;
}
#inputBox {
    background-color: #fafbfc;
    border: 1px solid #dfe4ea;
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 14px;
    color: #2b333d;
    selection-background-color: #b9d0f5;
}
#inputBox:focus {
    border-color: #1e6fff;
    background-color: #ffffff;
}
#sendBtn {
    background-color: #1e6fff;
    color: #ffffff;
    border: none;
    border-radius: 10px;
    padding: 8px 22px;
    font-size: 14px;
    font-weight: bold;
}
#sendBtn:hover {
    background-color: #1256d6;
}
#sendBtn:pressed {
    background-color: #0e48b3;
}

/* ---------- 状态栏 ---------- */
#statusBar {
    background-color: #ffffff;
    border-top: 1px solid #e2e6ec;
    color: #8a94a6;
    font-size: 12px;
}

/* ---------- 设置对话框 ---------- */
QDialog QLabel#dialogTitle {
    font-size: 16px;
    font-weight: bold;
    color: #1e3a6e;
}
QDialog QGroupBox {
    border: 1px solid #dfe4ea;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 8px;
    background-color: #ffffff;
}
QDialog QGroupBox::title {
    color: #1e6fff;
    font-size: 13px;
    font-weight: bold;
    padding: 0 6px;
}
QDialog QLineEdit, QDialog QSpinBox, QDialog QDoubleSpinBox {
    background-color: #f4f6f9;
    border: 1px solid #dfe4ea;
    border-radius: 6px;
    padding: 5px 8px;
}
QDialog QLineEdit:focus {
    border-color: #1e6fff;
}
QCheckBox {
    color: #2b333d;
    font-size: 13px;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #b9c2cf;
    background-color: #ffffff;
}
QCheckBox::indicator:checked {
    background-color: #1e6fff;
    border-color: #1e6fff;
}
QPushButton {
    background-color: #f0f3f7;
    border: 1px solid #dfe4ea;
    border-radius: 8px;
    padding: 6px 16px;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #e4ecfb;
    border-color: #b9d0f5;
    color: #1e6fff;
}
QPushButton#primaryBtn {
    background-color: #1e6fff;
    color: #ffffff;
    border: none;
}
QPushButton#primaryBtn:hover {
    background-color: #1256d6;
}

/* ---------- 日志与记忆 ---------- */
QPlainTextEdit#logBox, QPlainTextEdit#memBox {
    background-color: #f7f9fc;
    border: 1px solid #dfe4ea;
    border-radius: 8px;
    font-family: "Consolas", "Microsoft YaHei";
    font-size: 12px;
    color: #3d4653;
}
QListWidget#memList {
    background-color: #ffffff;
    border: 1px solid #dfe4ea;
    border-radius: 8px;
    color: #2b333d;
}
QListWidget#memList::item {
    padding: 6px 8px;
    border-bottom: 1px solid #f0f3f7;
}

QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #c9d2de;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #a9b6c8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""
