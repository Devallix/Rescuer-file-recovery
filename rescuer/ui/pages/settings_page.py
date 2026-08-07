from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from rescuer.core.app_context import AppContext
from rescuer.core.theme import PALETTES
from rescuer.ui.pages.base import Page, PageHeader


class SettingsPage(Page):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Settings page")
        self._ctx = AppContext.instance()

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(PageHeader("Settings", "Application preferences are stored locally."))

        appearance = SectionCard("Appearance")
        self._theme_combo = QComboBox()
        for name in PALETTES:
            self._theme_combo.addItem(name.capitalize(), name)
        self._theme_combo.setCurrentText(
            str(self._ctx.config.get("appearance.theme")).capitalize()
        )
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        appearance.form.addRow("Theme", self._theme_combo)
        root.addWidget(appearance)

        updates = SectionCard("Updates")
        self._check_updates = QCheckBox("Check for updates automatically")
        self._check_updates.setChecked(bool(self._ctx.config.get("general.check_updates", True)))
        self._check_updates.toggled.connect(self._on_check_updates_changed)
        updates.form.addRow("", self._check_updates)

        self._endpoint_edit = QLineEdit(str(self._ctx.config.get("updates.endpoint", "")))
        self._endpoint_edit.setPlaceholderText("https://example.com/version.json")
        self._endpoint_edit.textChanged.connect(self._on_endpoint_changed)
        updates.form.addRow("Update endpoint", self._endpoint_edit)

        self._channel_combo = QComboBox()
        self._channel_combo.addItems(["stable", "beta", "dev"])
        self._channel_combo.setCurrentText(str(self._ctx.config.get("updates.channel", "stable")))
        self._channel_combo.currentTextChanged.connect(self._on_channel_changed)
        updates.form.addRow("Channel", self._channel_combo)
        root.addWidget(updates)

        self._check_now_btn = QPushButton("Check now")
        self._check_now_btn.setObjectName("Ghost")
        self._check_now_btn.clicked.connect(self._check_now)
        root.addWidget(self._check_now_btn)

        signatures = SectionCard("Signatures")
        self._custom_dir_edit = QLineEdit(str(self._ctx.config.get("signatures.custom_dir", "")))
        self._custom_dir_edit.setPlaceholderText("C:\\Rescuer\\custom_signatures")
        self._custom_dir_edit.textChanged.connect(self._on_custom_dir_changed)
        signatures.form.addRow("Custom signatures folder", self._custom_dir_edit)
        root.addWidget(signatures)

        data = SectionCard("Data management")
        clear_btn = QPushButton("Delete scans older than 30 days")
        clear_btn.setObjectName("Danger")
        clear_btn.clicked.connect(self._clear_old_scans)
        data.form.addRow("", clear_btn)
        root.addWidget(data)

        root.addStretch(1)

    def _on_theme_changed(self) -> None:
        theme = self._theme_combo.currentData()
        self._ctx.config.set("appearance.theme", theme)
        self._ctx.events.theme_changed.emit(theme)

    def _on_check_updates_changed(self, checked: bool) -> None:
        self._ctx.config.set("general.check_updates", checked)

    def _on_endpoint_changed(self, text: str) -> None:
        self._ctx.config.set("updates.endpoint", text)

    def _on_channel_changed(self, text: str) -> None:
        self._ctx.config.set("updates.channel", text)

    def _on_custom_dir_changed(self, text: str) -> None:
        self._ctx.config.set("signatures.custom_dir", text)

    def _check_now(self) -> None:
        self._check_now_btn.setEnabled(False)
        self._check_now_btn.setText("Checking…")
        from rescuer.core.worker_pool import WorkerPool
        from rescuer.engine.updates.checker import check_for_updates
        pool = WorkerPool()
        endpoint = self._endpoint_edit.text() or self._ctx.config.get("updates.endpoint", "")
        current_version = getattr(self._ctx, "app", None) and getattr(self._ctx.app, "applicationVersion", lambda: "")() or "0.1.0"

        def _done(result):
            self._check_now_btn.setEnabled(True)
            self._check_now_btn.setText("Check now")
            if result is None:
                QMessageBox.information(self, "Up to date", "You are running the latest version.")
            else:
                QMessageBox.information(
                    self,
                    "Update available",
                    f"Version {result.version} is available.\n\n{result.notes}",
                )

        def _error(exc):
            self._check_now_btn.setEnabled(True)
            self._check_now_btn.setText("Check now")
            QMessageBox.warning(self, "Update check failed", str(exc))

        pool.submit(check_for_updates, current_version, endpoint, on_done=_done, on_error=_error)

    def _clear_old_scans(self) -> None:
        import datetime
        answer = QMessageBox.question(
            self,
            "Clear old scans",
            "Delete all scans and associated files older than 30 days?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat(sep=" ", timespec="seconds")
        old_scans = self._ctx.db.query(
            "SELECT id FROM scans WHERE finished_at IS NOT NULL AND finished_at < ?",
            (cutoff,),
        )
        scan_ids = [row["id"] for row in old_scans]
        if not scan_ids:
            QMessageBox.information(self, "Clear old scans", "No old scans to delete.")
            return
        for sid in scan_ids:
            self._ctx.db.execute("DELETE FROM scans WHERE id = ?", (sid,))
        QMessageBox.information(self, "Clear old scans", f"Deleted {len(scan_ids)} old scan(s).")


class SectionCard(QFrame):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(heading)

        self.form = QFormLayout()
        self.form.setSpacing(12)
        layout.addLayout(self.form)
