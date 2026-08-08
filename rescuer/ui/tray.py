from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from rescuer import APP_NAME
from rescuer.paths import Paths


class SystemTray(QSystemTrayIcon):
    def __init__(self, window, icon: QIcon | None = None) -> None:
        super().__init__(icon or QIcon(str(Paths.img_dir / "logo.png")), window)
        self._window = window

        menu = QMenu()
        open_action = menu.addAction("Open Rescuer")
        open_action.triggered.connect(self._show_window)
        menu.addSeparator()
        self._scan_status = menu.addAction("Idle")
        self._scan_status.setEnabled(False)
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)
        self.setContextMenu(menu)

        self.setToolTip(APP_NAME)
        self.activated.connect(self._on_activated)
        self.show()

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    def _show_window(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def _quit(self) -> None:
        self._window.set_quitting(True)
        QApplication.quit()

    def set_scan_count(self, count: int) -> None:
        if count:
            label = f"{count} scan(s) in progress"
            self._scan_status.setText(label)
            self.setToolTip(f"{APP_NAME} — {label}")
        else:
            self._scan_status.setText("Idle")
            self.setToolTip(APP_NAME)

    def notify(self, title: str, message: str) -> None:
        self.showMessage(
            title,
            message,
            QSystemTrayIcon.MessageIcon.Information,
            8000,
        )
