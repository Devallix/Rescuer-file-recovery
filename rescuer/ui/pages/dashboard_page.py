from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rescuer.core.app_context import AppContext
from rescuer.core.worker_pool import WorkerPool
from rescuer.engine.device.detector import DeviceDetector, VolumeInfo
from rescuer.ui.pages.base import Page, PageHeader
from rescuer.ui.widgets.cards import StatCard
from rescuer.ui.widgets.ring import RingWidget


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
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


class StorageRingCard(QFrame):
    def __init__(self, volume: VolumeInfo, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumHeight(250)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.ring = RingWidget()
        self.ring.setMinimumSize(140, 140)
        self.ring.set_value(volume.used_percent)
        layout.addWidget(self.ring, alignment=Qt.AlignmentFlag.AlignCenter)

        label = QLabel(
            f"{volume.mount_point or 'Volume'} · {volume.label or 'Local Disk'} — {volume.file_system or 'Unknown FS'}"
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setProperty("muted", True)
        layout.addWidget(label)

        usage = QLabel(
            f"{_human(volume.used_bytes)} used · {_human(volume.free_bytes)} free"
        )
        usage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        usage.setWordWrap(True)
        usage.setProperty("faint", True)
        layout.addWidget(usage)


class DashboardPage(Page):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Dashboard page")
        self._ctx = AppContext.instance()
        self._detector = DeviceDetector()
        self._pool = WorkerPool()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)

        container = QWidget()
        self._scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        self._header = PageHeader(
            "Dashboard",
            "Overview of your storage, recent recovery activity, and system health.",
        )
        root.addWidget(self._header)

        root.addWidget(self._build_blocked_banner())

        self._stats_row = QHBoxLayout()
        self._stats_row.setSpacing(14)
        self._total_storage = StatCard("TOTAL STORAGE")
        self._free_space = StatCard("FREE SPACE")
        self._drive_count = StatCard("CONNECTED DRIVES")
        self._last_recovery = StatCard("LAST RECOVERY")
        for card in (self._total_storage, self._free_space, self._drive_count, self._last_recovery):
            self._stats_row.addWidget(card, 1)
        root.addLayout(self._stats_row)

        section = QLabel("Storage")
        section.setStyleSheet("font-size: 15px; font-weight: 600; margin-top: 6px;")
        root.addWidget(section)

        self._rings_row = QHBoxLayout()
        self._rings_row.setSpacing(14)
        root.addLayout(self._rings_row)

        quick = QLabel("Quick Actions")
        quick.setStyleSheet("font-size: 15px; font-weight: 600; margin-top: 6px;")
        root.addWidget(quick)

        actions = QHBoxLayout()
        actions.setSpacing(14)
        recover_btn = QPushButton("New Recovery Wizard")
        recover_btn.setObjectName("Primary")
        actions.addWidget(recover_btn)
        scan_btn = QPushButton("Quick Scan")
        actions.addWidget(scan_btn)
        img_btn = QPushButton("Create Disk Image")
        actions.addWidget(img_btn)
        theme_btn = QPushButton("Toggle theme")
        theme_btn.setObjectName("Ghost")
        theme_btn.clicked.connect(self._toggle_theme)
        actions.addWidget(theme_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        root.addWidget(self._build_steps_card())

        root.addWidget(self._build_recent_card())

        root.addStretch(1)

        self._loading = QLabel("Detecting storage…")
        self._loading.setProperty("muted", True)
        root.addWidget(self._loading)

        recover_btn.clicked.connect(lambda: self._ctx.events.quick_action_requested.emit("wizard"))
        scan_btn.clicked.connect(lambda: self._ctx.events.quick_action_requested.emit("quick_scan"))
        img_btn.clicked.connect(lambda: self._ctx.events.quick_action_requested.emit("image"))
        self._ctx.events.scan_blocked.connect(self._show_blocked)

    def _build_blocked_banner(self) -> QWidget:
        banner = QFrame()
        banner.setObjectName("Card")
        banner.setStyleSheet(
            "#Card { border: 1px solid #B45309; background: #3B2A12; border-radius: 10px; }"
            "QLabel { color: #FDE68A; }"
        )
        banner.setVisible(False)
        self._banner = banner

        layout = QVBoxLayout(banner)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title = QLabel("Scan could not start")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        self._banner_text = QLabel("")
        self._banner_text.setWordWrap(True)
        self._banner_text.setProperty("muted", True)
        layout.addWidget(self._banner_text)

        row = QHBoxLayout()
        retry = QPushButton("Scan Recycle Bin instead")
        retry.setObjectName("Primary")
        retry.clicked.connect(lambda: self._ctx.events.quick_action_requested.emit("recycle_scan"))
        dismiss = QPushButton("Dismiss")
        dismiss.setObjectName("Ghost")
        dismiss.clicked.connect(lambda: banner.setVisible(False))
        row.addWidget(retry)
        row.addWidget(dismiss)
        row.addStretch(1)
        layout.addLayout(row)
        return banner

    def _show_blocked(self, device: str, reason: str) -> None:
        self._banner_text.setText(
            f"Scanning {device} directly requires administrator privileges:\n{reason}\n\n"
            "To scan this volume directly, close the app and reopen it as "
            "administrator.\n\n"
            "Files deleted into the Recycle Bin can still be restored to their original "
            "locations without admin rights."
        )
        self._banner.setVisible(True)

    def _build_steps_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        title = QLabel("How to recover a deleted file")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(title)

        steps = [
            "1.  Start the Recovery Wizard (or Quick Scan) and choose the drive the file was on.",
            "2.  Pick a scan method — Quick (fast, filesystem metadata) or Deep (slow, whole-device carving).",
            "3.  Wait for the scan; review the candidates and their quality stars in the Results step.",
            "4.  Choose a destination folder and click Recover selected / Recover all.",
            "5.  Generate an HTML, PDF, or CSV report to document the outcome.",
            "Tip: use a different destination drive than the one being recovered, and stop using the source drive immediately after deletion.",
        ]
        for text in steps:
            line = QLabel(text)
            line.setWordWrap(True)
            line.setProperty("muted", True)
            line.setStyleSheet("font-size: 12.5px;")
            layout.addWidget(line)

        return card

    def _build_recent_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        title = QLabel("Recent recoveries")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(title)

        ctx = AppContext.instance()
        rows = ctx.db.query(
            "SELECT s.id, s.mode, s.device_id, s.finished_at, s.recovered_count "
            "FROM scans s WHERE s.status = 'completed' ORDER BY s.id DESC LIMIT 5"
        )
        if not rows:
            empty = QLabel("No recoveries yet. Start the Recovery Wizard to begin.")
            empty.setProperty("muted", True)
            empty.setWordWrap(True)
            layout.addWidget(empty)
        else:
            for row in rows:
                text = (
                    f"Scan #{row['id']} · {row['mode']} · "
                    f"{row['recovered_count']} file(s) recovered · {row['finished_at'] or ''}"
                )
                line = QLabel(text)
                line.setWordWrap(True)
                line.setProperty("muted", True)
                line.setStyleSheet("font-size: 12.5px;")
                layout.addWidget(line)
        return card

    def refresh(self) -> None:
        self._pool.submit(self._detector.list_volumes, on_done=self._on_volumes, on_error=self._on_error)

    def _toggle_theme(self) -> None:
        ctx = AppContext.instance()
        current = ctx.config.get("appearance.theme", "dark")
        new_theme = "light" if current == "dark" else "dark"
        ctx.config.set("appearance.theme", new_theme)
        ctx.events.theme_changed.emit(new_theme)

    def _clear_rings(self) -> None:
        while self._rings_row.count():
            item = self._rings_row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _on_volumes(self, volumes: list[VolumeInfo]) -> None:
        self._clear_rings()
        total = sum(v.capacity for v in volumes)
        free = sum(v.free_bytes for v in volumes)
        self._total_storage.set_value(_human(total))
        self._total_storage.set_subtitle(f"{len(volumes)} mount point(s)")
        self._free_space.set_value(_human(free))
        self._free_space.set_subtitle(f"{_human(total - free) if total else '0 B'} in use")
        self._drive_count.set_value(str(len(volumes)))
        self._drive_count.set_subtitle("detected by the system")

        ctx = AppContext.instance()
        last = ctx.db.query_one(
            "SELECT finished_at, recovered_count FROM scans "
            "WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
        )
        if last:
            self._last_recovery.set_value(f"{last['recovered_count']} files")
            self._last_recovery.set_subtitle(last["finished_at"] or "recently")
        else:
            self._last_recovery.set_value("—")
            self._last_recovery.set_subtitle("no recoveries yet")

        for volume in volumes[:4]:
            card = StorageRingCard(volume)
            self._rings_row.addWidget(card, 1)

        if not volumes:
            self._loading.setText("No storage volumes detected.")
        else:
            self._loading.setText(f"Showing {len(volumes)} storage volume(s).")

    def _on_error(self, exc: Exception) -> None:
        self._loading.setText(f"Failed to detect storage: {exc}")
