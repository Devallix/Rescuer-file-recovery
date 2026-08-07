from PySide6.QtCore import Qt, QPropertyAnimation, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow, QMenuBar, QStackedWidget, QStatusBar, QWidget

from rescuer import APP_NAME, APP_TAGLINE, APP_TAGLINE
from rescuer.core.app_context import AppContext
from rescuer.core.theme import get_palette
from rescuer.integrations.windows.admin import is_admin
from rescuer.ui.navigation import NavItem, NavRail
from rescuer.ui.pages.dashboard_page import DashboardPage
from rescuer.ui.pages.drives_page import DrivesPage
from rescuer.ui.pages.reports_page import ReportsPage
from rescuer.ui.pages.results_page import ResultsPage
from rescuer.ui.pages.settings_page import SettingsPage
from rescuer.ui.pages.wizard_page import WizardPage

NAV_ITEMS = [
    NavItem("dashboard", "Dashboard", "dashboard", "Ctrl+1"),
    NavItem("drives", "Drives", "drives", "Ctrl+2"),
    NavItem("wizard", "Recovery Wizard", "wizard", "Ctrl+N"),
    NavItem("results", "Results", "results", "Ctrl+3"),
    NavItem("reports", "Reports", "reports", "Ctrl+4"),
    NavItem("settings", "Settings", "settings", "Ctrl+,"),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._ctx = AppContext.instance()
        self.setWindowTitle(f"{APP_NAME} — {APP_TAGLINE}")
        self.resize(1280, 820)
        self.setMinimumSize(960, 640)

        self._nav = NavRail(NAV_ITEMS)
        self._nav.navigate.connect(self._on_navigate)

        self._stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
        self._anims: set[QPropertyAnimation] = set()
        self._build_pages()

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._nav)
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._init_statusbar()
        self._init_menubar()

        self._ctx.events.theme_changed.connect(self._apply_theme_name)
        self._ctx.events.open_device_requested.connect(self._on_open_device)
        self._ctx.events.quick_action_requested.connect(self._on_quick_action)
        self._nav.select("dashboard")

    def _on_open_device(self, source) -> None:
        self._nav.select("wizard")
        if source is not None:
            self._wizard.open_with_source(source)

    def _on_quick_action(self, key: str) -> None:
        if key == "wizard":
            self._nav.select("wizard")
        elif key == "quick_scan":
            self._nav.select("wizard")
            self._wizard.start_quick_scan()
        elif key == "recycle_scan":
            self._nav.select("wizard")
            self._wizard.start_recycle_scan_for()
        elif key == "image":
            self._nav.select("drives")

    def _build_pages(self) -> None:
        self._wizard = WizardPage()
        self._register("dashboard", DashboardPage())
        self._register("drives", DrivesPage())
        self._register("wizard", self._wizard)
        self._register("results", ResultsPage())
        self._register("reports", ReportsPage())
        self._register("settings", SettingsPage())

    def _register(self, key: str, page: QWidget) -> None:
        self._pages[key] = page
        self._stack.addWidget(page)

    def _on_navigate(self, key: str) -> None:
        current = self._stack.currentWidget()
        target = self._pages[key]
        if current is not None and current is not target:
            self._fade(current, 1.0, 0.0, lambda: self._switch_page(current, target, key))
        else:
            self._switch_page(current, target, key)

    def _switch_page(self, old, target, key: str) -> None:
        self._stack.setCurrentWidget(target)
        self._fade(target, 0.0, 1.0, None)
        if hasattr(target, "refresh"):
            target.refresh()

    def _fade(self, page: QWidget, start: float, end: float, on_finished=None) -> None:
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(120)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.finished.connect(lambda: self._animation_finished(anim, effect, page, on_finished))
        self._anims.add(anim)
        anim.start()

    def _animation_finished(self, anim: QPropertyAnimation, effect, page: QWidget, on_finished=None) -> None:
        self._anims.discard(anim)
        if page.graphicsEffect() is effect:
            page.setGraphicsEffect(None)
        anim.deleteLater()
        if on_finished is not None:
            on_finished()

    def _init_statusbar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        admin = "Administrator" if is_admin() else "Standard user"
        self._status_label = QLabel(f"{APP_NAME} · {admin}")
        self._status_label.setObjectName("statusText")
        bar.addWidget(self._status_label)
        bar.addPermanentWidget(QLabel("Powered by Devallix"))

    def _init_menubar(self) -> None:
        menubar = QMenuBar()
        help_menu = menubar.addMenu("Help")
        user_guide = QAction("User Guide", self)
        user_guide.triggered.connect(self._open_user_guide)
        help_menu.addAction(user_guide)
        about = QAction("About", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)
        self.setMenuBar(menubar)

    def _open_user_guide(self) -> None:
        import os
        from pathlib import Path
        guide = Path(__file__).resolve().parents[2] / "docs" / "USER_GUIDE.md"
        if guide.exists():
            os.startfile(str(guide))
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "User Guide", "Open docs/USER_GUIDE.md in your editor.")

    def _apply_theme_name(self, theme: str) -> None:
        palette = get_palette(theme)
        self._nav.set_palette(palette)
        for page in self._pages.values():
            if hasattr(page, "on_theme_changed"):
                page.on_theme_changed(palette)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mod = event.modifiers()
        if mod == Qt.KeyboardModifier.ControlModifier:
            mapping = {
                Qt.Key.Key_1: "dashboard",
                Qt.Key.Key_2: "drives",
                Qt.Key.Key_3: "results",
                Qt.Key.Key_4: "reports",
                Qt.Key.Key_Comma: "settings",
                Qt.Key.Key_N: "wizard",
            }
            page = mapping.get(key)
            if page and page in self._pages:
                self._nav.select(page)
                return
        if key == Qt.Key.Key_F1:
            self._show_about()
            return
        super().keyPressEvent(event)

    def _show_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from rescuer import __version__
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> v{__version__}<br>"
            f"<i>{APP_TAGLINE}</i><br><br>"
            "Professional file recovery & data restoration suite for Windows.<br><br>"
            "Built with Python 3.13+, PySide6, and The Sleuth Kit.<br><br>"
            "Documentation: docs/USER_GUIDE.md<br>"
            "Repository: https://github.com/rescuer-app/rescuer<br><br>"
            "Proprietary. All rights reserved.",
        )
