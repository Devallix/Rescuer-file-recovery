import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from rescuer.core.app_context import AppContext
from rescuer.core.worker_pool import WorkerPool
from rescuer.engine.device.detector import DeviceDetector, VolumeInfo
from rescuer.engine.imaging.controller import ImagingController
from rescuer.engine.models import RecoverySource
from rescuer.integrations.windows.admin import is_admin
from rescuer.ui.pages.base import Page, PageHeader


def _human(size: int) -> str:
    if size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(size)
    unit = units[0]
    for u in units:
        if value < 1024:
            unit = u
            break
        value /= 1024
    return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"


class DrivesPage(Page):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Drive Manager page")
        self._detector = DeviceDetector()
        self._pool = WorkerPool()

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(PageHeader("Drive Manager", "Every storage device connected to this system."))

        top = QHBoxLayout()
        self._status = QLabel("Loading drives…")
        self._status.setProperty("muted", True)
        top.addWidget(self._status)
        top.addStretch(1)
        self._scan_btn = QPushButton("Scan selected")
        self._scan_btn.setObjectName("Primary")
        self._scan_btn.setEnabled(False)
        self._scan_btn.clicked.connect(self._scan_selected)
        top.addWidget(self._scan_btn)
        self._image_btn = QPushButton("Create image…")
        self._image_btn.setObjectName("Ghost")
        self._image_btn.clicked.connect(self._image_selected)
        top.addWidget(self._image_btn)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self._refresh_btn)
        root.addLayout(top)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["Drive", "Label", "File System", "Capacity", "Used", "Free", "Used %", "Type / Health"]
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_selection)
        root.addWidget(self._table, 1)

        self._imaging = QFrame()
        self._imaging.setObjectName("Card")
        img_layout = QVBoxLayout(self._imaging)
        img_layout.setContentsMargins(14, 10, 14, 10)
        img_layout.setSpacing(6)
        self._img_label = QLabel("")
        self._img_label.setProperty("muted", True)
        img_layout.addWidget(self._img_label)
        self._img_progress = QProgressBar()
        self._img_progress.setRange(0, 1000)
        img_layout.addWidget(self._img_progress)
        img_actions = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Danger")
        cancel.clicked.connect(self._cancel_image)
        img_actions.addWidget(cancel)
        img_actions.addStretch(1)
        img_layout.addLayout(img_actions)
        self._imaging.setVisible(False)
        root.addWidget(self._imaging)

        self._volumes: list[VolumeInfo] = []
        self._ctx = AppContext.instance()

        self._imaging_ctl = ImagingController()
        self._imaging_ctl.progress.connect(self._on_image_progress)
        self._imaging_ctl.finished.connect(self._on_image_finished)
        self._imaging_ctl.failed.connect(self._on_image_failed)

    def _on_selection(self) -> None:
        self._scan_btn.setEnabled(
            not self._imaging_ctl.running and bool(self._table.selectedItems())
        )

    def refresh(self) -> None:
        if self._imaging_ctl.running:
            return
        self._status.setText("Loading drives…")
        self._table.setRowCount(0)
        self._pool.submit(self._detector.list_volumes, on_done=self._on_volumes, on_error=self._on_error)

    def _on_volumes(self, volumes: list[VolumeInfo]) -> None:
        self._volumes = volumes
        self._table.setRowCount(len(volumes))
        for row, v in enumerate(volumes):
            vals = [
                v.mount_point or "—",
                v.label or "—",
                v.file_system or "—",
                _human(v.capacity),
                _human(v.used_bytes),
                _human(v.free_bytes),
                f"{v.used_percent * 100:.0f}%",
                ("Removable" if v.is_removable else "Fixed") + (f" · {v.health}" if v.health else ""),
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col in (3, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, col, item)
        self._status.setText(f"{len(volumes)} volume(s) detected.")

    def _on_error(self, exc: Exception) -> None:
        self._status.setText(f"Failed to load drives: {exc}")

    def _selected_volume(self) -> VolumeInfo | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._volumes):
            return self._volumes[idx]
        return None

    def _scan_selected(self) -> None:
        if self._imaging_ctl.running:
            return
        vol = self._selected_volume()
        if vol is None:
            return
        source = RecoverySource(
            kind="volume",
            mount_point=vol.mount_point,
            label=vol.label or "",
            fs_type=vol.file_system or "",
            size=vol.capacity,
        )
        self._ctx.events.open_device_requested.emit(source)

    def _image_selected(self) -> None:
        if self._imaging_ctl.running:
            self._status.setText("Imaging already in progress.")
            return
        vol = self._selected_volume()
        if vol is None:
            self._status.setText("Select a volume to image first.")
            return
        default = os.path.join(os.path.expanduser("~/Documents"), f"{vol.mount_point.strip(':') or 'disk'}.img")
        path, _ = QFileDialog.getSaveFileName(self, "Save disk image", default, "Disk image (*.img);;Raw (*.raw);;All files (*)")
        if not path:
            return
        message = (
            f"Create a byte-for-byte image of {vol.mount_point} to {path}?\n\n"
            "This can take a long time and requires read access."
        )
        if not is_admin():
            message += (
                "\n\nNote: byte-level read access to a live drive requires administrator "
                "privileges. The image may not be created unless the app is run as "
                "administrator."
            )
        answer = QMessageBox.question(self, "Create disk image", message)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._img_progress.setValue(0)
        self._img_progress.setRange(0, 1000)
        self._img_label.setText(f"Imaging {vol.mount_point}…")
        self._imaging.setVisible(True)
        self._set_controls_enabled(False)
        self._imaging_ctl.start(vol.mount_point, path)

    def _cancel_image(self) -> None:
        self._imaging_ctl.cancel()
        self._img_label.setText("Cancelling…")

    def _on_image_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._img_progress.setRange(0, 1000)
            self._img_progress.setValue(int(done / total * 1000))
            self._img_label.setText(f"{_human(done)} of {_human(total)} copied")
        else:
            self._img_progress.setRange(0, 0)

    def _on_image_finished(self, result) -> None:
        self._imaging.setVisible(False)
        self._set_controls_enabled(True)
        self._status.setText(
            f"Image saved to {result.path} ({_human(result.size)} in {result.seconds:.0f}s, "
            f"{result.mb_per_sec:.1f} MB/s)"
        )

    def _on_image_failed(self, error: str) -> None:
        self._imaging.setVisible(False)
        self._set_controls_enabled(True)
        self._status.setText(f"Imaging failed: {error}")

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._scan_btn.setEnabled(enabled and bool(self._table.selectedItems()))
        self._image_btn.setEnabled(enabled)
        self._refresh_btn.setEnabled(enabled)
