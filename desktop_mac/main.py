"""Launch the native PySide6 desktop client."""

from __future__ import annotations

import os
import sys
from typing import Any, Callable

from PySide6.QtCore import QByteArray, QObject, QRunnable, QSettings, QThreadPool, Qt, QEvent, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QTextBlockFormat, QTextCursor
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from desktop_mac.api import SelfIndexApi


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.operation = operation
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.finished.emit(self.operation())
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class SafeMarkdownBrowser(QTextBrowser):
    """Render archive text without fetching resources named by its Markdown."""

    def loadResource(self, resource_type, name):
        return None


class DockReopenFilter(QObject):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.window = window

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is QApplication.instance() and event.type() == QEvent.Type.Quit:
            if self.window._quit_authorized:
                self.window._quit_authorized = False
            else:
                self.window._request_quit()
                return True
        if event.type() == QEvent.Type.ApplicationActivate and self.window.isHidden():
            self.window.show_window()
        return False


def search_icon() -> QIcon:
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#5b6575"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawEllipse(4, 3, 12, 12)
    painter.drawLine(14, 14, 21, 21)
    painter.end()
    return QIcon(pixmap)


def claim_desktop_instance(on_activate: Callable[[], None], name: str | None = None) -> QLocalServer | None:
    server_name = name or f"local.selfindex.desktop.{os.getuid()}"

    def activate_existing() -> bool:
        socket = QLocalSocket()
        socket.connectToServer(server_name)
        connected = socket.waitForConnected(500)
        if connected:
            socket.write(b"activate")
            socket.waitForBytesWritten(500)
        socket.close()
        return connected

    server = QLocalServer()
    if not server.listen(server_name):
        if activate_existing():
            return None
        QLocalServer.removeServer(server_name)
        if not server.listen(server_name):
            if activate_existing():
                return None
            raise RuntimeError(f"Cannot claim desktop instance: {server.errorString()}")

    def receive_activation() -> None:
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            on_activate()
            connection.disconnectFromServer()
            connection.deleteLater()

    server.newConnection.connect(receive_activation)
    return server


class MainWindow(QMainWindow):
    def __init__(self, ui_settings: QSettings | None = None) -> None:
        super().__init__()
        self.ui_settings = ui_settings if ui_settings is not None else QSettings("SelfIndex", "Desktop")
        self._layout_ready = False
        self.layout_save_timer = QTimer(self)
        self.layout_save_timer.setSingleShot(True)
        self.layout_save_timer.setInterval(500)
        self.layout_save_timer.timeout.connect(self._save_ui_state)
        self.api = SelfIndexApi()
        self.pool = QThreadPool.globalInstance()
        self._workers: set[Worker] = set()
        self.results: list[dict[str, Any]] = []
        self.search_generation = 0
        self.detail_generation = 0
        self.current_memory_id: str | None = None
        self.loaded_detail: dict[str, Any] | None = None
        self._saving = False
        self._pending_navigation: Callable[[], None] | None = None
        self._quit_authorized = False
        self.home_search_timer = QTimer(self)
        self.home_search_timer.setSingleShot(True)
        self.home_search_timer.setInterval(380)
        self.home_search_timer.timeout.connect(self._search)
        self._build_ui()
        self.setWindowTitle("SelfIndex")
        self.resize(1120, 760)
        self.setMinimumSize(760, 540)
        self._restore_ui_state()
        self._layout_ready = True
        QApplication.instance().aboutToQuit.connect(self._save_ui_state)
        self._set_status("正在连接…", "checking")
        self._run(self.api.health, self._health_ready, self._health_failed)

    def _build_ui(self) -> None:
        self.pages = QStackedWidget()
        home = QWidget()
        home.setObjectName("homePage")
        home_layout = QVBoxLayout(home)
        home_layout.setContentsMargins(32, 24, 32, 24)
        home_layout.addStretch(2)
        home_center = QWidget()
        home_center.setMaximumWidth(760)
        home_center_layout = QVBoxLayout(home_center)
        home_center_layout.setContentsMargins(0, 0, 0, 0)
        home_center_layout.setSpacing(28)
        brand = QLabel("SelfIndex")
        brand.setObjectName("landingBrand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        home_center_layout.addWidget(brand)
        divider = QFrame()
        divider.setObjectName("brandDivider")
        divider.setFixedHeight(1)
        divider.setFixedWidth(440)
        home_center_layout.addWidget(divider, alignment=Qt.AlignmentFlag.AlignHCenter)
        search_shell, self.home_query = self._make_search_shell(landing=True)
        self.home_query.textChanged.connect(self._schedule_home_search)
        home_center_layout.addWidget(search_shell)
        self.home_notice = QLabel("")
        self.home_notice.setObjectName("homeNotice")
        self.home_notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.home_notice.setWordWrap(True)
        home_center_layout.addWidget(self.home_notice)
        home_row = QHBoxLayout()
        home_row.setContentsMargins(0, 0, 0, 0)
        home_row.addStretch(1)
        home_row.addWidget(home_center, 5)
        home_row.addStretch(1)
        home_layout.addLayout(home_row)
        home_layout.addStretch(3)
        self.pages.addWidget(home)

        workspace = QWidget()
        workspace.setObjectName("workspacePage")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.setSpacing(16)
        self.home_button = QToolButton()
        self.home_button.setObjectName("homeButton")
        self.home_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.home_button.setToolTip("返回搜索首页")
        self.home_button.clicked.connect(self._show_home)
        header.addWidget(self.home_button)
        title = QLabel("SelfIndex")
        title.setObjectName("workspaceBrand")
        header.addWidget(title)
        header.addStretch()
        self.connection = QLabel("● 正在连接…")
        self.connection.setObjectName("connection")
        header.addWidget(self.connection, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)

        search_shell, self.query = self._make_search_shell(landing=False)
        layout.addWidget(search_shell)

        self.state = QLabel("输入关键词以搜索记忆。")
        self.state.setObjectName("muted")
        layout.addWidget(self.state)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setObjectName("results")
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentRowChanged.connect(self._select_result)
        self.list.setMinimumWidth(250)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(12, 0, 0, 0)
        detail_layout.setSpacing(10)
        self.detail_heading = QLabel("记忆详情")
        self.detail_heading.setObjectName("sectionTitle")
        detail_layout.addWidget(self.detail_heading)
        self.view_header = QWidget()
        view_header_layout = QVBoxLayout(self.view_header)
        view_header_layout.setContentsMargins(0, 0, 0, 0)
        view_header_layout.setSpacing(5)
        self.title_view = QLabel("")
        self.title_view.setObjectName("detailTitle")
        self.title_view.setWordWrap(True)
        self.author_view = QLabel("")
        self.author_view.setObjectName("muted")
        view_header_layout.addWidget(self.title_view)
        view_header_layout.addWidget(self.author_view)
        self.time_label = QLabel("时间：—")
        self.time_label.setObjectName("muted")
        view_header_layout.addWidget(self.time_label)
        detail_layout.addWidget(self.view_header)

        self.editor_meta = QWidget()
        editor_meta_layout = QVBoxLayout(self.editor_meta)
        editor_meta_layout.setContentsMargins(0, 0, 0, 0)
        editor_meta_layout.setSpacing(9)
        self.title_field = QLineEdit()
        self.title_field.setPlaceholderText("标题")
        self.title_field.setClearButtonEnabled(True)
        self.author_field = QLineEdit()
        self.author_field.setPlaceholderText("作者")
        self.author_field.setClearButtonEnabled(True)
        editor_meta_layout.addWidget(self.title_field)
        editor_meta_layout.addWidget(self.author_field)
        detail_layout.addWidget(self.editor_meta)

        self.content_stack = QStackedWidget()
        self.content_preview = SafeMarkdownBrowser()
        self.content_preview.setObjectName("markdownPreview")
        self.content_preview.setOpenLinks(False)
        self.content_preview.anchorClicked.connect(self._open_markdown_link)
        self.content_field = QPlainTextEdit()
        self.content_field.setPlaceholderText("原始 Markdown")
        self.content_field.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.content_stack.addWidget(self.content_preview)
        self.content_stack.addWidget(self.content_field)
        detail_layout.addWidget(self.content_stack, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        self.edit_button = QPushButton("编辑")
        self.edit_button.clicked.connect(self._begin_edit)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self._cancel_edit)
        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        detail_layout.addLayout(actions)
        self.index_state = QLabel("")
        self.index_state.setObjectName("muted")
        detail_layout.addWidget(self.index_state)

        self.splitter.addWidget(self.list)
        self.splitter.addWidget(detail_panel)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 6)
        self.splitter.splitterMoved.connect(self._schedule_ui_state_save)
        layout.addWidget(self.splitter, 1)
        self.pages.addWidget(workspace)
        self.setCentralWidget(self.pages)
        self._set_editing(False)
        self._set_detail_enabled(False)
        self._build_menu()
        self.setStyleSheet("""
            QWidget#homePage, QWidget#workspacePage { background: #ffffff; color: #243447; }
            QLabel#landingBrand { color: #243447; font-size: 64px; font-weight: 700; }
            QFrame#brandDivider { background: #dbe3ec; border: 0; }
            QLabel#homeNotice { color: #ad3b32; font-size: 13px; }
            QLabel#workspaceBrand { color: #243447; font-size: 23px; font-weight: 700; }
            QLabel#sectionTitle { color: #243447; font-size: 16px; font-weight: 600; }
            QLabel#detailTitle { color: #243447; font-size: 20px; font-weight: 650; }
            QLabel#muted { color: #66736f; }
            QLabel#connection { color: #66736f; font-size: 12px; }
            QFrame#landingSearchShell, QFrame#workspaceSearchShell {
                background: #f3f6fa; border: 1px solid #d7dce2; border-radius: 24px;
            }
            QFrame#landingSearchShell { border-radius: 34px; }
            QToolButton#searchIcon {
                background: #eef2f7; border: 0; border-radius: 21px;
            }
            QToolButton#searchIcon:hover { background: #e2e9f2; }
            QLineEdit#landingSearchInput, QLineEdit#workspaceSearchInput {
                background: transparent; border: 0; color: #243447; padding: 0 6px;
                selection-background-color: #cfe1f3;
            }
            QLineEdit#landingSearchInput { font-size: 20px; }
            QLineEdit#workspaceSearchInput { font-size: 15px; }
            QToolButton#homeButton { background: transparent; border: 0; padding: 5px; }
            QToolButton#homeButton:hover { background: #eef2f7; border-radius: 5px; }
            QLineEdit, QListWidget, QPlainTextEdit { background: white; border: 1px solid #dbe3ec; border-radius: 5px; padding: 9px; }
            QLineEdit { min-height: 22px; }
            QListWidget { padding: 0; }
            QListWidget::item { padding: 12px 10px; border-bottom: 1px solid #e9edf2; }
            QListWidget::item:selected { background: #edf3f9; color: #243447; }
            QPlainTextEdit { font-size: 13px; }
            QTextBrowser#markdownPreview {
                background: white; border: 0; padding: 0; color: #243447; font-size: 15px;
            }
            QPushButton { background: #edf2f6; border: 0; border-radius: 5px; padding: 9px 16px; min-width: 54px; }
            QPushButton:hover { background: #e3eaf1; }
            QPushButton:disabled { color: #89938f; background: #f2f4f6; }
            QPushButton#primary { background: #243447; color: white; font-weight: 600; }
            QPushButton#primary:hover { background: #344c65; }
            QSplitter::handle { background: transparent; width: 10px; }
        """)
        self.home_query.setFocus()

    def _make_search_shell(self, *, landing: bool) -> tuple[QFrame, QLineEdit]:
        shell = QFrame()
        shell.setObjectName("landingSearchShell" if landing else "workspaceSearchShell")
        shell.setFixedHeight(72 if landing else 48)
        shell.setMaximumWidth(760 if landing else 16777215)
        row = QHBoxLayout(shell)
        row.setContentsMargins(8, 5, 12, 5)
        row.setSpacing(10)
        button = QToolButton()
        button.setObjectName("searchIcon")
        button.setIcon(search_icon())
        button.setIconSize(QPixmap(24, 24).size())
        button.setFixedSize(50 if landing else 38, 50 if landing else 38)
        button.setToolTip("搜索")
        button.clicked.connect(self._search)
        if not landing:
            self.workspace_search_button = button
        row.addWidget(button)
        query = QLineEdit()
        query.setObjectName("landingSearchInput" if landing else "workspaceSearchInput")
        query.setPlaceholderText("输入关键词或句子，搜索本地记忆库…")
        query.setClearButtonEnabled(True)
        query.returnPressed.connect(self._search)
        row.addWidget(query, 1)
        return shell, query

    def _restore_ui_state(self) -> None:
        geometry = self.ui_settings.value("window/geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)
        splitter_state = self.ui_settings.value("window/splitter")
        if isinstance(splitter_state, QByteArray) and not splitter_state.isEmpty():
            self.splitter.restoreState(splitter_state)

    def _schedule_ui_state_save(self) -> None:
        if self._layout_ready:
            self.layout_save_timer.start()

    def _save_ui_state(self) -> None:
        if not self._layout_ready:
            return
        self.layout_save_timer.stop()
        self.ui_settings.setValue("window/geometry", self.saveGeometry())
        if self.pages.currentIndex() == 1 and self.splitter.isVisible():
            self.ui_settings.setValue("window/splitter", self.splitter.saveState())
        self.ui_settings.sync()

    def _schedule_home_search(self, value: str) -> None:
        self.home_search_timer.stop()
        if value.strip():
            self.home_search_timer.start()

    def _show_home(self) -> None:
        if self._is_editing() or self._saving:
            self._request_navigation(self._show_home)
            return
        self._save_ui_state()
        self.home_search_timer.stop()
        self.search_generation += 1
        self.detail_generation += 1
        self.current_memory_id = None
        self.results = []
        self.list.clear()
        self.query.clear()
        self.home_query.blockSignals(True)
        self.home_query.clear()
        self.home_query.blockSignals(False)
        self._set_detail_enabled(False)
        self.pages.setCurrentIndex(0)
        self.home_query.setFocus()

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("SelfIndex")
        show_action = menu.addAction("显示窗口")
        show_action.triggered.connect(self.show_window)
        menu.addSeparator()
        quit_action = menu.addAction("退出 SelfIndex")
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self._request_quit)

    def _is_editing(self) -> bool:
        return self.content_stack.currentIndex() == 1 and self.loaded_detail is not None

    def _is_dirty(self) -> bool:
        if not self._is_editing() or self.loaded_detail is None:
            return False
        return any((
            self.title_field.text() != self.loaded_detail["title"],
            self.author_field.text() != self.loaded_detail["author"],
            self.content_field.toPlainText() != self.loaded_detail["content"],
        ))

    def _request_navigation(self, action: Callable[[], None]) -> bool:
        if self._saving:
            self.index_state.setText("正在保存，请稍候。")
            return False
        if self._is_editing():
            if self._is_dirty():
                choice = QMessageBox.question(
                    self, "未保存的修改", "保存当前修改后再离开吗？",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Save,
                )
                if choice == QMessageBox.StandardButton.Save:
                    self._pending_navigation = action
                    self._save()
                    return False
                if choice != QMessageBox.StandardButton.Discard:
                    return False
            self._cancel_edit()
        action()
        return True

    def _request_quit(self) -> None:
        def quit_app() -> None:
            self._quit_authorized = True
            QApplication.instance().quit()

        self._request_navigation(quit_app)

    def _run(self, operation: Callable[[], Any], success: Callable[[Any], None], failure: Callable[[str], None]) -> None:
        worker = Worker(operation)
        self._workers.add(worker)

        def completed(value: Any) -> None:
            try:
                success(value)
            finally:
                self._workers.discard(worker)

        def failed(message: str) -> None:
            try:
                failure(message)
            finally:
                self._workers.discard(worker)

        worker.signals.finished.connect(completed)
        worker.signals.failed.connect(failed)
        self.pool.start(worker)

    def _set_status(self, text: str, state: str) -> None:
        colors = {"ok": "#176b50", "error": "#ad3b32", "checking": "#66736f"}
        self.connection.setText("● " + text)
        self.connection.setStyleSheet(f"color: {colors[state]}; padding: 8px 12px; background: #e9eeeb; border-radius: 6px;")

    def _set_detail_enabled(self, enabled: bool) -> None:
        for widget in (self.title_field, self.author_field, self.content_field, self.edit_button):
            widget.setEnabled(enabled)
        if not enabled:
            self.loaded_detail = None
            self.title_field.clear()
            self.author_field.clear()
            self.content_field.clear()
            self.content_preview.clear()
            self.title_view.clear()
            self.author_view.clear()
            self.time_label.setText("时间：—")
            self.index_state.clear()

    def _set_editing(self, editing: bool) -> None:
        for widget in (self.title_field, self.author_field, self.content_field):
            widget.setReadOnly(not editing)
            widget.setEnabled(not self._saving)
        self.view_header.setVisible(not editing)
        self.editor_meta.setVisible(editing)
        self.content_stack.setCurrentIndex(1 if editing else 0)
        self.edit_button.setVisible(not editing)
        self.cancel_button.setVisible(editing)
        self.save_button.setVisible(editing)
        self.save_button.setEnabled(not self._saving)
        self.cancel_button.setEnabled(not self._saving)
        self.list.setEnabled(not editing and not self._saving)
        self.home_button.setEnabled(not editing and not self._saving)
        self.query.setEnabled(not editing and not self._saving)
        self.workspace_search_button.setEnabled(not self._saving)

    def _health_ready(self, payload: dict[str, Any]) -> None:
        if payload.get("ok") is True and payload.get("service") == "selfindex":
            self._set_status(f"已连接 · v{payload.get('version', '未知')}", "ok")
            self.home_notice.clear()
        else:
            self._health_failed("健康检查响应不符合预期。")

    def _health_failed(self, message: str) -> None:
        self._set_status("服务未连接", "error")
        self.state.setText(message + " 请确认本地服务已启动。")
        self.home_notice.setText(self.state.text())

    def _search(self) -> None:
        if self._is_editing() or self._saving:
            self._request_navigation(self._search)
            return
        from_home = self.pages.currentIndex() == 0
        query = (self.home_query if from_home else self.query).text().strip()
        if not query:
            if from_home:
                self.home_notice.setText("请输入搜索内容。")
            else:
                self.state.setText("请输入搜索内容。")
            return
        self.home_search_timer.stop()
        self.home_notice.clear()
        if from_home:
            self.query.setText(query)
            self.pages.setCurrentIndex(1)
        else:
            self.home_query.blockSignals(True)
            self.home_query.setText(query)
            self.home_query.blockSignals(False)
        self.search_generation += 1
        generation = self.search_generation
        self.detail_generation += 1
        self.current_memory_id = None
        self.results = []
        self.list.clear()
        self._set_editing(False)
        self._set_detail_enabled(False)
        self.query.setEnabled(False)
        self.state.setText("正在搜索…")
        self._run(lambda: self.api.search(query), lambda data: self._search_ready(data, generation), lambda error: self._search_failed(error, generation))

    def _search_ready(self, payload: dict[str, Any], generation: int) -> None:
        if generation != self.search_generation:
            return
        self.query.setEnabled(True)
        items = payload.get("results")
        if not isinstance(items, list):
            self._search_failed("搜索响应缺少有效结果。", generation)
            return
        self.results = [item for item in items if isinstance(item, dict)]
        if not self.results:
            self.state.setText("没有找到符合条件的记忆。")
            return
        self.state.setText(f"找到 {payload.get('count', len(self.results))} 条记忆")
        for result in self.results:
            title = str(result.get("title") or "未命名记忆")
            summary = str(result.get("summary") or result.get("preview") or result.get("content") or "")
            source = str(result.get("source") or "")
            timestamp = str(result.get("created_at") or "")
            self.list.addItem(QListWidgetItem(f"{title}\n{summary}\n{source}  {timestamp}".strip()))
        self.list.setCurrentRow(0)

    def _search_failed(self, message: str, generation: int) -> None:
        if generation != self.search_generation:
            return
        self.query.setEnabled(True)
        self.state.setText("搜索失败：" + message)
        self._set_status("服务连接异常", "error")

    def _select_result(self, row: int) -> None:
        if row < 0 or row >= len(self.results):
            return
        if self._is_editing() or self._saving:
            if not self._request_navigation(lambda: self._select_result(row)):
                previous_row = next(
                    (index for index, result in enumerate(self.results)
                     if result.get("memory_unit_id") == self.current_memory_id), -1
                )
                self.list.blockSignals(True)
                self.list.setCurrentRow(previous_row)
                self.list.blockSignals(False)
            return
        if self.list.currentRow() != row:
            self.list.blockSignals(True)
            self.list.setCurrentRow(row)
            self.list.blockSignals(False)
        memory_id = self.results[row].get("memory_unit_id")
        if not memory_id:
            return
        self.current_memory_id = str(memory_id)
        self.detail_generation += 1
        generation = self.detail_generation
        self._set_editing(False)
        self._set_detail_enabled(False)
        self._set_detail_enabled(True)
        self.edit_button.setEnabled(False)
        self.content_preview.setPlainText("正在加载详情…")
        self._run(lambda: self.api.memory(str(memory_id)), lambda data: self._detail_ready(data, str(memory_id), generation), lambda error: self._detail_failed(error, str(memory_id), generation))

    def _detail_is_current(self, memory_id: str, generation: int) -> bool:
        return self.current_memory_id == memory_id and self.detail_generation == generation

    def _detail_ready(self, payload: dict[str, Any], memory_id: str, generation: int) -> None:
        if not self._detail_is_current(memory_id, generation):
            return
        memory = payload.get("memory_unit")
        raw = payload.get("raw_document")
        if not isinstance(memory, dict) or not isinstance(raw, dict):
            self._detail_failed("详情响应格式不正确。", memory_id, generation)
            return
        self.loaded_detail = {
            "title": str(raw.get("title") or ""),
            "author": str(raw.get("author") or ""),
            "content": str(raw.get("content") or memory.get("content") or ""),
            "created_at": str(raw.get("created_at") or ""),
            "expected_revision_id": str(raw.get("latest_revision_id") or memory.get("revision_id") or ""),
            "expected_edit_version": int(raw.get("edit_version") or 0),
            "historical": bool(raw.get("historical")),
            "source_backed": raw.get("source") == "markdown" and raw.get("source_type") == "note_file",
        }
        self._show_loaded_detail()
        self.index_state.clear()
        self.edit_button.setEnabled(not self.loaded_detail["historical"])

    def _show_loaded_detail(self) -> None:
        if self.loaded_detail is None:
            return
        detail = self.loaded_detail
        self.title_view.setText(detail["title"] or "未命名记忆")
        self.author_view.setText("作者：" + (detail["author"] or "—"))
        self.time_label.setText("时间：" + (detail["created_at"] or "—"))
        self.title_field.setText(detail["title"])
        self.author_field.setText(detail["author"])
        self.title_field.setReadOnly(bool(detail.get("source_backed")))
        self.author_field.setReadOnly(bool(detail.get("source_backed")))
        self.content_field.setPlainText(detail["content"])
        self._render_markdown(detail["content"])
        self.content_preview.verticalScrollBar().setValue(0)

    def _render_markdown(self, content: str) -> None:
        self.content_preview.setMarkdown(content)
        document = self.content_preview.document()
        block = document.begin()
        cursor = QTextCursor(document)
        while block.isValid():
            block_format = block.blockFormat()
            block_format.setLineHeight(145.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            if block_format.headingLevel():
                block_format.setTopMargin(16)
                block_format.setBottomMargin(8)
            elif block.textList() is not None:
                block_format.setTopMargin(2)
                block_format.setBottomMargin(2)
            else:
                block_format.setTopMargin(2)
                block_format.setBottomMargin(10)
            cursor.setPosition(block.position())
            cursor.setBlockFormat(block_format)
            block = block.next()

    def _detail_failed(self, message: str, memory_id: str, generation: int) -> None:
        if not self._detail_is_current(memory_id, generation):
            return
        self.content_preview.setPlainText("加载详情失败：" + message)
        self.edit_button.setEnabled(False)

    def _begin_edit(self) -> None:
        if self.current_memory_id and self.loaded_detail is not None and self.edit_button.isEnabled():
            self.index_state.clear()
            self._set_editing(True)
            (self.content_field if self.loaded_detail.get("source_backed") else self.title_field).setFocus()

    def _cancel_edit(self) -> None:
        if self._saving:
            return
        self._show_loaded_detail()
        self._set_editing(False)

    def _open_markdown_link(self, url: QUrl) -> None:
        if not url.scheme() and not url.path() and url.fragment():
            self.content_preview.scrollToAnchor(url.fragment())
        elif url.scheme() in {"http", "https", "mailto"}:
            QDesktopServices.openUrl(url)

    def _save(self) -> None:
        memory_id = self.current_memory_id
        if not memory_id or not self._is_editing() or self._saving:
            return
        body = {
            "title": self.title_field.text(),
            "author": self.author_field.text(),
            "content": self.content_field.toPlainText(),
            "expected_revision_id": str(self.loaded_detail.get("expected_revision_id") or ""),
            "expected_edit_version": int(self.loaded_detail.get("expected_edit_version") or 0),
        }
        self._saving = True
        self._set_editing(True)
        self.index_state.setText("正在保存…")
        generation = self.detail_generation
        self._run(
            lambda: self.api.update_memory(memory_id, **body),
            lambda result: self._save_ready(result, memory_id, generation, body),
            lambda error: self._save_failed(error, memory_id, generation),
        )

    def _save_ready(self, result: tuple[int, dict[str, Any]], memory_id: str, generation: int, body: dict[str, str]) -> None:
        self._saving = False
        if not self._detail_is_current(memory_id, generation):
            self._pending_navigation = None
            self.state.setText("已保存，当前详情已变化，请重新打开查看。")
            return
        status, payload = result
        normalized = {
            "title": body["title"].strip() or "Untitled document",
            "author": body["author"].strip() or "unknown",
            "content": body["content"].strip(),
        }
        server_document = payload.get("document")
        if isinstance(server_document, dict) and all(
            isinstance(server_document.get(field), str) for field in normalized
        ):
            normalized = {field: server_document[field] for field in normalized}
        self.loaded_detail = {
            **normalized,
            "created_at": self.loaded_detail["created_at"] if self.loaded_detail else "",
            "expected_revision_id": str(payload.get("revision_id") or body["expected_revision_id"]),
            "expected_edit_version": int(payload.get("edit_version", body["expected_edit_version"])),
            "historical": False,
            "source_backed": bool(self.loaded_detail.get("source_backed")) if self.loaded_detail else False,
        }
        self._show_loaded_detail()
        self._set_editing(False)
        new_memory_id = payload.get("memory_unit_id")
        if isinstance(new_memory_id, str) and new_memory_id:
            self.current_memory_id = new_memory_id
            row = self.list.currentRow()
            if 0 <= row < len(self.results):
                self.results[row]["memory_unit_id"] = new_memory_id
                self.results[row]["title"] = normalized["title"]
                self.results[row]["summary"] = normalized["content"][:120]
                source = str(self.results[row].get("source") or "")
                timestamp = str(self.results[row].get("created_at") or "")
                self.list.item(row).setText(
                    f"{normalized['title']}\n{normalized['content'][:120]}\n{source}  {timestamp}".strip()
                )
        index_status = str(payload.get("index_status") or ("ready" if status == 200 else "pending"))
        source_status = str(payload.get("source_status") or "not_applicable")
        if source_status == "pending":
            message = "已保存到资料库，源文件待写入"
        else:
            message = "已保存，索引已就绪" if index_status == "ready" else "已保存，索引未就绪"
        self.index_state.setText(message)
        self.state.setText(message)
        pending = self._pending_navigation
        self._pending_navigation = None
        if pending is not None:
            pending()

    def _save_failed(self, message: str, memory_id: str, generation: int) -> None:
        self._saving = False
        self._pending_navigation = None
        if not self._detail_is_current(memory_id, generation):
            self.state.setText("保存失败：" + message)
            return
        self._set_editing(True)
        self.index_state.setText("保存失败：" + message)

    def show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and self.isHidden():
            self.show_window()

    def moveEvent(self, event: QEvent) -> None:
        super().moveEvent(event)
        self._schedule_ui_state_save()

    def resizeEvent(self, event: QEvent) -> None:
        super().resizeEvent(event)
        self._schedule_ui_state_save()

    def closeEvent(self, event: Any) -> None:
        self._save_ui_state()
        event.ignore()
        self.hide()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SelfIndex")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont(".AppleSystemUIFont", 13))
    activation_requests: list[None] = []

    def request_activation() -> None:
        if window is None:
            activation_requests.append(None)
        else:
            window.show_window()

    window: MainWindow | None = None
    server = claim_desktop_instance(request_activation)
    if server is None:
        return 0
    window = MainWindow()
    reopen_filter = DockReopenFilter(window)
    app.installEventFilter(reopen_filter)
    window.show()
    if activation_requests:
        window.show_window()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
