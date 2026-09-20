"""Voyager 1 科研助手 - 主窗口(侧边栏导航 + 简洁科技风)。"""
import html
import threading
import time
import traceback

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.agent import Agent
from app.core.curiosity import Curiosity
from app.core.initiative import Initiative
from app.core.procs import ProcsWatch
from app.core.rumination import Rumination
from app.core.screenwatch import ScreenWatch
from app.core.situation import SituationJudge
from app.ui.solar_map import SolarMapWidget


def _to_html(text):
    """文本转 HTML:转义 + 换行 -> <br> + 链接可点。"""
    text = html.escape(text or "")
    text = text.replace("\n", "<br>")
    import re

    text = re.sub(
        r"(https?://[^\s<>\"']+)",
        r'<a href="\1" style="color:#1e6fff;">\1</a>',
        text,
    )
    return text


class Bridge(QObject):
    """工作线程 -> UI 主线程的信号桥。"""

    token = Signal(str)
    turn_done = Signal(str)
    turn_error = Signal(str)
    search_requested = Signal(str)
    status = Signal(str)
    log = Signal(str)
    initiative_msg = Signal(str)
    ruminate_done = Signal()


class MainWindow(QMainWindow):
    def __init__(self, config, memory, llm, searcher, backdoor=None):
        super().__init__()
        self.config = config
        self.memory = memory
        self.llm = llm
        self.searcher = searcher
        self.backdoor = backdoor
        self.bridge = Bridge()
        self._worker = None
        self._ruminate_thread = None
        self._ruminating = False
        self._search_event = threading.Event()
        self._search_decision = False
        self._last_user_ts = time.time()
        self._current_bubble = None
        self._current_raw = ""
        self._last_screen_ts = 0.0
        self._screen_busy = False
        self._procs_busy = False
        self._bg_drag = None  # 太阳系右键拖拽起点

        self.setWindowTitle("Voyager 1 · 深空科研助手")
        self.resize(1080, 740)
        self._build_ui()
        self._connect()

        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(60_000)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start()

        self._screen_timer = QTimer(self)
        self._screen_timer.setInterval(30_000)
        self._screen_timer.timeout.connect(self._on_screen_tick)
        self._screen_timer.start()

    # ---------- UI ----------

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 头部
        header = QWidget()
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 12, 18, 12)
        glyph = QLabel("◈")
        glyph.setObjectName("titleGlyph")
        title = QLabel("VOYAGER 1")
        title.setObjectName("titleLabel")
        subtitle = QLabel("深空科研助手 · DeepSeek")
        subtitle.setObjectName("subtitleLabel")
        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDot")
        self.status_label = QLabel("待命")
        self.status_label.setObjectName("statusLabel")
        hl.addWidget(glyph)
        hl.addWidget(title)
        hl.addSpacing(8)
        hl.addWidget(subtitle)
        self.ruminate_btn = QPushButton("沉思")
        self.ruminate_btn.setObjectName("ruminateBtn")
        self.ruminate_btn.setToolTip("手动触发一次沉思(回顾对话、提炼记忆、自主检索)")
        hl.addSpacing(16)
        hl.addWidget(self.ruminate_btn)
        hl.addStretch(1)
        hl.addWidget(self.status_dot)
        hl.addWidget(self.status_label)
        root.addWidget(header)

        # 主体:侧边栏 + 页面
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(150)
        for name in ("对话", "沉思日志", "研发日志", "学习笔记", "设置"):
            self.sidebar.addItem(name)
        bl.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_chat_page())
        self.pages.addWidget(self._build_log_page())
        self.pages.addWidget(self._build_facts_page())
        self.pages.addWidget(self._build_notes_page())
        self.pages.addWidget(self._build_settings_page())
        bl.addWidget(self.pages, 1)
        root.addWidget(body, 1)

        self.setCentralWidget(central)

    def _build_chat_page(self):
        page = QWidget()
        self._chat_page = page
        # 监听页面尺寸变化,让太阳系背景始终铺满(窗口自适应)
        page.installEventFilter(self)
        # 中层背景:太阳系实时地图(普通子控件置底,最下层白底由它绘制)
        self.solar_map = SolarMapWidget(page)

        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setObjectName("chatScroll")
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        chat_host = QWidget()
        chat_host.setObjectName("chatArea")
        # 确保 QSS 透明背景真正生效(普通 QWidget 需 WA_StyledBackground)
        chat_host.setAttribute(Qt.WA_StyledBackground, True)
        chat_host.setAttribute(Qt.WA_TranslucentBackground)
        chat_host.setAutoFillBackground(False)
        self.chat_layout = QVBoxLayout(chat_host)
        self.chat_layout.setContentsMargins(20, 16, 20, 16)
        self.chat_layout.setSpacing(10)
        self.chat_layout.addStretch(1)
        self.chat_scroll.setWidget(chat_host)
        lay.addWidget(self.chat_scroll, 1)

        panel = QWidget()
        panel.setObjectName("inputPanel")
        pl = QHBoxLayout(panel)
        pl.setContentsMargins(18, 10, 18, 10)
        self.input_box = QLineEdit()
        self.input_box.setObjectName("inputBox")
        self.input_box.setPlaceholderText("向 Voyager 1 提问…（Enter 发送）")
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("sendBtn")
        pl.addWidget(self.input_box, 1)
        pl.addWidget(self.send_btn)
        lay.addWidget(panel)

        # 太阳系置于最底(白底 -> 太阳系 -> 对话框 的三层顺序)
        self.solar_map.lower()
        self.solar_map.setGeometry(page.rect())
        return page

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 布局更新完成后同步太阳系背景几何(直接读 rect 会拿到旧尺寸)
        QTimer.singleShot(0, self._sync_solar_map)

    def _sync_solar_map(self):
        page = getattr(self, "_chat_page", None)
        if page is not None:
            self.solar_map.setGeometry(page.rect())

    def _build_log_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 14, 16, 14)
        tip = QLabel("沉思日志:后台活动记录(沉思/好奇心/检索/屏幕感知)")
        tip.setObjectName("subtitleLabel")
        lay.addWidget(tip)
        self.log_box = QPlainTextEdit()
        self.log_box.setObjectName("logBox")
        self.log_box.setReadOnly(True)
        lay.addWidget(self.log_box, 1)
        return page

    def _build_facts_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 14, 16, 14)
        tip = QLabel("研发日志:长期记住的研究事实与开拓者信息(选中后可删除)")
        tip.setObjectName("subtitleLabel")
        lay.addWidget(tip)
        self.facts_list = QListWidget()
        self.facts_list.setObjectName("memList")
        lay.addWidget(self.facts_list, 1)
        row = QHBoxLayout()
        self.fact_del_btn = QPushButton("删除选中")
        self.fact_clear_btn = QPushButton("清空全部")
        row.addStretch(1)
        row.addWidget(self.fact_del_btn)
        row.addWidget(self.fact_clear_btn)
        lay.addLayout(row)
        return page

    def _build_notes_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 14, 16, 14)
        tip = QLabel("学习笔记:Voyager 沉淀的知识与兴趣笔记(选中后可删除)")
        tip.setObjectName("subtitleLabel")
        lay.addWidget(tip)
        self.notes_list = QListWidget()
        self.notes_list.setObjectName("memList")
        lay.addWidget(self.notes_list, 1)
        row = QHBoxLayout()
        self.note_del_btn = QPushButton("删除选中")
        self.note_clear_btn = QPushButton("清空全部")
        row.addStretch(1)
        row.addWidget(self.note_del_btn)
        row.addWidget(self.note_clear_btn)
        lay.addLayout(row)
        return page

    def _build_settings_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 14, 16, 14)

        g1 = QGroupBox("模型")
        f1 = QHBoxLayout(g1)
        f1.addWidget(QLabel("API Key"))
        self.key_edit = QLineEdit(self.config.get("deepseek_api_key", default=""))
        self.key_edit.setEchoMode(QLineEdit.Password)
        f1.addWidget(self.key_edit, 1)
        lay.addWidget(g1)

        g2 = QGroupBox("模型参数")
        f2 = QGridLayout(g2)
        f2.addWidget(QLabel("模型"), 0, 0)
        self.model_edit = QLineEdit(self.config.get("model", default="deepseek-chat"))
        f2.addWidget(self.model_edit, 0, 1)
        f2.addWidget(QLabel("温度"), 1, 0)
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(float(self.config.get("temperature", default=0.7)))
        f2.addWidget(self.temp_spin, 1, 1)
        f2.addWidget(QLabel("最大输出"), 2, 0)
        self.max_spin = QSpinBox()
        self.max_spin.setRange(256, 8192)
        self.max_spin.setSingleStep(256)
        self.max_spin.setValue(int(self.config.get("max_tokens", default=2048)))
        f2.addWidget(self.max_spin, 2, 1)
        lay.addWidget(g2)

        g3 = QGroupBox("功能")
        v3 = QVBoxLayout(g3)
        self.cb_search = QCheckBox("科研搜索(arXiv/PubMed/期刊优先)")
        self.cb_ansys = QCheckBox("Ansys Workbench 仿真接口(对话中自动生成并执行 journal)")
        self.cb_rumination = QCheckBox("沉思(空闲时回顾与检索)")
        self.cb_curiosity = QCheckBox("好奇心(定期自主探索新课题)")
        self.cb_initiative = QCheckBox("主动汇报(空闲时主动说话)")
        self.cb_screen = QCheckBox("屏幕感知(观察你在做什么)")
        self.cb_situation = QCheckBox("情景判断(推断任务状态)")
        self.cb_procs = QCheckBox("进程观察(只读任务管理器)")
        for cb, key in (
            (self.cb_search, "search.enabled"),
            (self.cb_ansys, "ansys.enabled"),
            (self.cb_rumination, "rumination.enabled"),
            (self.cb_curiosity, "curiosity.enabled"),
            (self.cb_initiative, "initiative.enabled"),
            (self.cb_screen, "screen.enabled"),
            (self.cb_situation, "situation.enabled"),
            (self.cb_procs, "procs.enabled"),
        ):
            cb.setChecked(bool(self.config.get(*key.split("."), default=True)))
            v3.addWidget(cb)
        lay.addWidget(g3)

        # 密钥验证(开发者模式,与对话暗号等效)
        g4 = QGroupBox("密钥验证(开发者模式)")
        v4 = QVBoxLayout(g4)
        self.bd_status = QLabel("状态:未验证")
        self.bd_status.setObjectName("subtitleLabel")
        v4.addWidget(self.bd_status)
        r1 = QHBoxLayout()
        self.key1_edit = QLineEdit()
        self.key1_edit.setEchoMode(QLineEdit.Password)
        self.key1_edit.setPlaceholderText("第一层密钥")
        self.key1_btn = QPushButton("验证第一层")
        r1.addWidget(self.key1_edit, 1)
        r1.addWidget(self.key1_btn)
        v4.addLayout(r1)
        r2 = QHBoxLayout()
        self.key2_edit = QLineEdit()
        self.key2_edit.setEchoMode(QLineEdit.Normal)  # 中文密钥,明文显示
        self.key2_edit.setPlaceholderText("第二层密钥(需先通过第一层)")
        self.key2_btn = QPushButton("验证第二层")
        r2.addWidget(self.key2_edit, 1)
        r2.addWidget(self.key2_btn)
        v4.addLayout(r2)
        # 第一层验证通过之前,不显示第二层输入区
        self.key2_edit.setVisible(False)
        self.key2_btn.setVisible(False)
        self.lock_btn = QPushButton("锁定")
        self.lock_btn.setObjectName("primaryBtn")
        v4.addWidget(self.lock_btn)
        lay.addWidget(g4)

        # 界面显示
        g5 = QGroupBox("界面显示")
        v5 = QHBoxLayout(g5)
        v5.addWidget(QLabel("对话记录背景透明度"))
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.2, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setDecimals(2)
        self.opacity_spin.setValue(float(self.config.get("ui", "bubble_opacity", default=0.9) or 0.9))
        v5.addWidget(self.opacity_spin)
        v5.addWidget(QLabel("(越小越透明,文字保持黑色)"))
        v5.addStretch(1)
        lay.addWidget(g5)

        self.save_btn = QPushButton("保存设置")
        self.save_btn.setObjectName("primaryBtn")
        self.save_msg = QLabel("")
        self.save_msg.setObjectName("subtitleLabel")
        lay.addWidget(self.save_btn)
        lay.addWidget(self.save_msg)
        lay.addStretch(1)
        return page

    def _connect(self):
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
        self.sidebar.currentRowChanged.connect(self._on_page_changed)

        self.send_btn.clicked.connect(self._on_send)
        self.input_box.returnPressed.connect(self._on_send)
        self.save_btn.clicked.connect(self._save_settings)
        self.ruminate_btn.clicked.connect(self._on_manual_ruminate)
        self.key1_btn.clicked.connect(self._verify_layer1)
        self.key2_btn.clicked.connect(self._verify_layer2)
        self.lock_btn.clicked.connect(self._lock_backdoor)
        self.fact_del_btn.clicked.connect(self._delete_selected_fact)
        self.fact_clear_btn.clicked.connect(self._clear_facts)
        self.note_del_btn.clicked.connect(self._delete_selected_note)
        self.note_clear_btn.clicked.connect(self._clear_notes)
        # 太阳系右键拖动旋转(滚动区会拦截 viewport 鼠标事件,用事件过滤器转发)
        self.chat_scroll.viewport().installEventFilter(self)

        b = self.bridge
        b.token.connect(self._on_token)
        b.turn_done.connect(self._on_turn_done)
        b.turn_error.connect(self._on_turn_error)
        b.status.connect(self._set_status)
        b.log.connect(self._append_log)
        b.initiative_msg.connect(lambda m: self._show_ai_message(m))
        b.ruminate_done.connect(self._on_ruminate_done)
        b.search_requested.connect(self._on_search_requested)

    def _on_page_changed(self, idx):
        if idx == 2:  # 研发日志
            self._refresh_facts()
        elif idx == 3:  # 学习笔记
            self._refresh_notes()
        elif idx == 4:  # 设置(刷新密钥状态)
            self._refresh_backdoor_status()

    # ---------- 太阳系背景右键旋转 ----------

    def eventFilter(self, obj, event):
        # UI 构建期间属性尚未齐备,先防御性短路
        if not (hasattr(self, "_chat_page") and hasattr(self, "solar_map")
                and hasattr(self, "chat_scroll")):
            return False
        # 聊天页尺寸变化:同步太阳系背景几何(布局更新后触发,精确铺满)
        if obj is self._chat_page and event.type() == QEvent.Resize:
            self.solar_map.setGeometry(self._chat_page.rect())
            return False
        if obj is self.chat_scroll.viewport():
            t = event.type()
            # Ctrl+滚轮:缩放太阳系(Ctrl 键按下时拦截,不滚动对话)
            if t == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
                self.solar_map.zoom_by(event.angleDelta().y())
                return True
            if t == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
                self._bg_drag = event.position()
                return True
            if t == QEvent.MouseMove and self._bg_drag is not None and event.buttons() & Qt.RightButton:
                p = event.position()
                self.solar_map.rotate_by(p.x() - self._bg_drag.x(), p.y() - self._bg_drag.y())
                self._bg_drag = p
                return True
            if t == QEvent.MouseButtonRelease and event.button() == Qt.RightButton:
                self._bg_drag = None
                return True
        return super().eventFilter(obj, event)

    # ---------- 密钥验证(开发者模式) ----------

    def _refresh_backdoor_status(self):
        if not self.backdoor:
            self.bd_status.setText("状态:未启用")
            self.key2_edit.setVisible(False)
            self.key2_btn.setVisible(False)
            return
        if self.backdoor.unlocked:
            self.bd_status.setText("状态:已解锁(创始者认知生效)")
        elif getattr(self.backdoor, "_layer1_passed", False):
            self.bd_status.setText("状态:第一层已验证,请输入第二层密钥")
        else:
            self.bd_status.setText("状态:未验证")
        # 第一层通过(或已解锁)才显示第二层输入区
        show2 = self.backdoor.unlocked or getattr(self.backdoor, "_layer1_passed", False)
        self.key2_edit.setVisible(show2)
        self.key2_btn.setVisible(show2)

    def _verify_layer1(self):
        if not self.backdoor:
            self._set_status("密钥验证未启用")
            return
        if self.backdoor.check_layer1(self.key1_edit.text()):
            self.key1_edit.clear()
            self._refresh_backdoor_status()
            self._set_status("第一层验证通过")
        else:
            self._set_status("第一层验证失败")

    def _verify_layer2(self):
        if not self.backdoor:
            self._set_status("密钥验证未启用")
            return
        if self.backdoor.check_layer2(self.key2_edit.text()):
            self.key2_edit.clear()
            self._refresh_backdoor_status()
            self._set_status("已解锁创始者认知")
        else:
            self._set_status("第二层验证失败(需先通过第一层)")

    def _lock_backdoor(self):
        if self.backdoor:
            self.backdoor.lock()
            self._refresh_backdoor_status()
            self._set_status("已锁定")

    def _refresh_facts(self):
        self.facts_list.clear()
        try:
            for f in self.memory.list_facts(limit=300):
                item = QListWidgetItem(f"{f['text']}")
                item.setData(Qt.UserRole, f["id"])
                self.facts_list.addItem(item)
        except Exception:
            pass

    def _refresh_notes(self):
        self.notes_list.clear()
        try:
            for n in self.memory.list_notes(limit=300):
                ts = time.strftime("%m-%d %H:%M", time.localtime(n["ts"])) if n["ts"] else ""
                tag = "兴趣" if n["kind"] == "curiosity" else "学习"
                item = QListWidgetItem(f"[{tag}] {n['topic']}  ({ts})")
                item.setData(Qt.UserRole, n["id"])
                item.setToolTip(n["content"][:200])
                self.notes_list.addItem(item)
        except Exception:
            pass

    # ---------- 记忆删除(连带删除对话记录) ----------

    def _delete_selected_fact(self):
        item = self.facts_list.currentItem()
        if item is None:
            self._set_status("请先选中要删除的事实")
            return
        fid = item.data(Qt.UserRole)
        if QMessageBox.question(
            self, "删除事实", "确定删除这条事实?将同时清空对话记录。"
        ) == QMessageBox.Yes:
            self.memory.delete_fact(fid)
            self.memory.clear_conversation()
            self._refresh_facts()
            self._set_status("已删除(对话记录已清空)")

    def _clear_facts(self):
        if QMessageBox.question(
            self, "清空研发日志", "确定清空全部事实?将同时清空对话记录,此操作不可恢复。"
        ) == QMessageBox.Yes:
            self.memory.clear_facts()
            self.memory.clear_conversation()
            self._refresh_facts()
            self._set_status("研发日志已清空(对话记录已清空)")

    def _delete_selected_note(self):
        item = self.notes_list.currentItem()
        if item is None:
            self._set_status("请先选中要删除的笔记")
            return
        nid = item.data(Qt.UserRole)
        if QMessageBox.question(
            self, "删除笔记", "确定删除这条笔记?将同时清空对话记录。"
        ) == QMessageBox.Yes:
            self.memory.delete_note(nid)
            self.memory.clear_conversation()
            self._refresh_notes()
            self._set_status("已删除(对话记录已清空)")

    def _clear_notes(self):
        if QMessageBox.question(
            self, "清空学习笔记", "确定清空全部笔记?将同时清空对话记录,此操作不可恢复。"
        ) == QMessageBox.Yes:
            self.memory.clear_notes()
            self.memory.clear_conversation()
            self._refresh_notes()
            self._set_status("学习笔记已清空(对话记录已清空)")

    # ---------- 聊天气泡 ----------

    def _bubble_style(self, kind):
        """按配置透明度生成气泡样式(文字保持不透明黑色/白色)。"""
        op = float(self.config.get("ui", "bubble_opacity", default=0.9) or 0.9)
        op = max(0.2, min(1.0, op))
        if kind == "user":
            return (
                f"QFrame#bubbleUser {{ background-color: rgba(30,111,255,{op});"
                " border-radius: 10px; border: none; }"
            )
        return (
            f"QFrame#bubbleAI {{ background-color: rgba(255,255,255,{op});"
            " border-radius: 10px; border: 1px solid #e2e6ec;"
            " border-left: 3px solid #c9a227; }"
        )

    def _add_bubble(self, kind, text_html):
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame()
        bubble.setObjectName("bubbleUser" if kind == "user" else "bubbleAI")
        bubble.setStyleSheet(self._bubble_style(kind))
        bl = QVBoxLayout(bubble)
        bl.setContentsMargins(14, 10, 14, 10)
        label = QLabel()
        label.setObjectName("bubbleUserLabel" if kind == "user" else "bubbleAILabel")
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        # 聊天文字可选中复制
        label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
        )
        label.setText(text_html)
        t = QLabel(time.strftime("%H:%M:%S"))
        t.setObjectName("bubbleTime")
        bl.addWidget(label)
        bl.addWidget(t, 0, Qt.AlignRight)
        if kind == "user":
            lay.addStretch(1)
            lay.addWidget(bubble, 0)
        else:
            lay.addWidget(bubble, 0)
            lay.addStretch(1)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, wrap)
        self._scroll_bottom()
        return label

    def _scroll_bottom(self):
        QTimer.singleShot(30, lambda: self.chat_scroll.verticalScrollBar().setValue(
            self.chat_scroll.verticalScrollBar().maximum()
        ))

    def _show_ai_message(self, text):
        self._add_bubble("ai", _to_html(text))

    # ---------- 发送与回复 ----------

    def _on_send(self):
        text = self.input_box.text().strip()
        if not text:
            return
        self.input_box.clear()
        self._last_user_ts = time.time()
        self._add_bubble("user", _to_html(text))
        self._run_turn(text)

    def _run_turn(self, text):
        if self._worker and self._worker.is_alive():
            self._set_status("上一次对话仍在进行")
            return
        self._set_status("思考中…")
        self._worker = threading.Thread(target=self._turn_worker, args=(text,), daemon=True)
        self._worker.start()

    def _turn_worker(self, text):
        agent = Agent(self.config, self.memory, self.llm, self.searcher, backdoor=self.backdoor)
        try:
            agent.run_turn(
                text,
                on_token=lambda c: self.bridge.token.emit(c),
                on_search_confirm=self._confirm_search,
                on_status=lambda s: self.bridge.status.emit(s),
            )
            self.bridge.turn_done.emit("")
        except Exception as e:
            self.bridge.turn_error.emit(str(e))

    def _on_token(self, chunk):
        if self._current_bubble is None:
            self._current_raw = ""
            self._current_bubble = self._add_bubble("ai", "")
        self._current_raw += chunk
        self._current_bubble.setText(_to_html(self._current_raw))
        self._scroll_bottom()

    def _on_turn_done(self, _):
        self._current_bubble = None
        self._current_raw = ""
        self._set_status("待命")
        self._last_user_ts = time.time()

    def _on_turn_error(self, message):
        self._current_bubble = None
        self._set_status(f"出错:{message}")
        self._add_bubble("ai", _to_html(f"⚠ {message}"))

    def _confirm_search(self, query):
        self._search_event.clear()
        self._search_decision = False
        self.bridge.search_requested.emit(query)
        self._search_event.wait(60)
        return self._search_decision

    def _on_search_requested(self, query):
        self._set_status(f"等待确认:检索「{query}」")
        box = QMessageBox(self)
        box.setWindowTitle("检索确认")
        box.setText(f"Voyager 1 需要检索网络:\n「{query}」")
        allow = box.addButton("允许检索", QMessageBox.AcceptRole)
        deny = box.addButton("拒绝", QMessageBox.RejectRole)
        box.exec()
        self._search_decision = box.clickedButton() is allow
        self._search_event.set()

    def _set_status(self, text):
        self.status_label.setText(text)

    def _append_log(self, line):
        self.log_box.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {line}")
        self.status_label.setText(line[:60])

    # ---------- 设置 ----------

    def _save_settings(self):
        self.config.set(self.key_edit.text().strip(), "deepseek_api_key")
        self.config.set(self.model_edit.text().strip() or "deepseek-chat", "model")
        self.config.set(self.temp_spin.value(), "temperature")
        self.config.set(self.max_spin.value(), "max_tokens")
        self.config.set(self.cb_search.isChecked(), "search", "enabled")
        self.config.set(self.cb_ansys.isChecked(), "ansys", "enabled")
        self.config.set(self.cb_rumination.isChecked(), "rumination", "enabled")
        self.config.set(self.cb_curiosity.isChecked(), "curiosity", "enabled")
        self.config.set(self.cb_initiative.isChecked(), "initiative", "enabled")
        self.config.set(self.cb_screen.isChecked(), "screen", "enabled")
        self.config.set(self.cb_situation.isChecked(), "situation", "enabled")
        self.config.set(self.cb_procs.isChecked(), "procs", "enabled")
        self.config.set(self.opacity_spin.value(), "ui", "bubble_opacity")
        self.config.save()
        self._apply_bubble_opacity()
        self.save_msg.setText("已保存 ✅")

    def _apply_bubble_opacity(self):
        """把新的透明度应用到已有气泡。"""
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            w = item.widget() if item else None
            if w is None or w.layout() is None:
                continue
            bubble = w.layout().itemAt(0).widget() if w.layout().count() else None
            if isinstance(bubble, QFrame) and bubble.objectName() in ("bubbleUser", "bubbleAI"):
                bubble.setStyleSheet(self._bubble_style(bubble.objectName()))

    # ---------- 后台:沉思 / 好奇 / 主动 / 屏幕 ----------

    def _on_manual_ruminate(self):
        if self._ruminating:
            self._set_status("已在沉思中…")
            return
        if self._worker and self._worker.is_alive():
            self._set_status("正在对话,稍后再沉思")
            return
        self._set_status("开始沉思…")
        self._start_ruminate()

    def _check_idle(self):
        if self._ruminating:
            return
        if self._worker and self._worker.is_alive():
            return
        enabled = bool(self.config.get("rumination", "enabled", default=True))
        minutes = int(self.config.get("rumination", "idle_minutes", default=5))
        if enabled and time.time() - self._last_user_ts > minutes * 60:
            self._start_ruminate()
            return
        self._check_initiative(relaxed=False)

    def _start_ruminate(self):
        if self._ruminating:
            return
        self._ruminating = True
        self._ruminate_thread = threading.Thread(target=self._run_ruminate, daemon=True)
        self._ruminate_thread.start()

    def _run_ruminate(self):
        try:
            rum = Rumination(
                self.config,
                self.memory,
                self.llm,
                self.searcher,
                on_status=lambda s: self.bridge.status.emit(s),
                on_log=lambda s: self.bridge.log.emit(s),
            )
            rum.run_once(force_curiosity=True)
        except Exception:
            traceback.print_exc()
        finally:
            self._ruminating = False
            self.bridge.ruminate_done.emit()

    def _on_ruminate_done(self):
        self._check_initiative(relaxed=True)

    def _check_initiative(self, relaxed=False):
        if self._worker and self._worker.is_alive():
            return
        if self._ruminating:
            return
        if self.input_box.text().strip():
            return
        idle_minutes = (time.time() - self._last_user_ts) / 60.0
        init = Initiative(self.config, self.memory, self.llm)
        if not init.due(idle_minutes=idle_minutes, force=relaxed):
            return
        threading.Thread(target=self._run_initiative, daemon=True).start()

    def _run_initiative(self):
        init = Initiative(self.config, self.memory, self.llm)
        try:
            msg = init.compose()
        except Exception:
            return
        if not msg:
            return
        self.memory.add_message("assistant", msg)
        self.memory.set_meta("last_initiative", str(time.time()))
        self.bridge.initiative_msg.emit(msg)

    def _on_screen_tick(self):
        cfg = self.config.get("screen", default={}) or {}
        if cfg.get("enabled", True):
            interval = max(10, int(cfg.get("interval_seconds", 60)))
            if (
                time.time() - self._last_screen_ts >= interval
                and not self._screen_busy
            ):
                self._last_screen_ts = time.time()
                self._screen_busy = True
                threading.Thread(target=self._run_screen_snapshot, daemon=True).start()
        pcfg = self.config.get("procs", default={}) or {}
        if pcfg.get("enabled", True):
            plast = float(self.memory.get_meta("last_procs", "0") or 0)
            if (
                time.time() - plast >= max(30, int(pcfg.get("interval_seconds", 60)))
                and not self._procs_busy
            ):
                self._procs_busy = True
                threading.Thread(target=self._run_procs_snapshot, daemon=True).start()

    def _run_procs_snapshot(self):
        try:
            watch = ProcsWatch(self.config, self.memory)
            changed, summary = watch.snapshot()
            if changed and summary:
                self.bridge.log.emit(f"【任务管理器】{summary}")
        except Exception:
            pass
        finally:
            self._procs_busy = False

    def _run_screen_snapshot(self):
        try:
            watch = ScreenWatch(self.config, self.memory)
            changed, summary = watch.snapshot()
            if changed and summary:
                self.bridge.log.emit(f"【屏幕感知】Voyager 观测到:{summary}")
            cfg = self.config.get("situation", default={}) or {}
            if cfg.get("enabled", True):
                last = float(self.memory.get_meta("last_situation", "0") or 0)
                interval = int(cfg.get("judge_interval_minutes", 10)) * 60
                if changed or time.time() - last >= interval:
                    judge = SituationJudge(self.config, self.memory, self.llm)
                    line = judge.judge()
                    self.memory.set_meta("last_situation", str(time.time()))
                    if line:
                        self.bridge.log.emit(f"【此刻感知】{line}")
        except Exception:
            pass
        finally:
            self._screen_busy = False
