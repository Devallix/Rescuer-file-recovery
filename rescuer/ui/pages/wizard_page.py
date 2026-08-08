import datetime
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rescuer.core.app_context import AppContext
from rescuer.core.worker_pool import WorkerPool
from rescuer.engine.device.detector import DeviceDetector
from rescuer.engine.models import RecoverySource, ScanConfig
from rescuer.engine.recovery.queue import RecoveryQueue
from rescuer.engine.scan.controller import ScanController
from rescuer.engine.signatures.registry import SignatureRegistry
from rescuer.ui.pages.base import Page, PageHeader
from rescuer.ui.widgets.stars import StarsLabel

STEPS = ["Device", "Scan mode", "Scanning", "Review", "Complete"]


def _human(size: int) -> str:
    if size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(size)
    for u in units:
        if value < 1024:
            return f"{int(value)} {u}" if u == "B" else f"{value:.1f} {u}"
        value /= 1024
    return f"{value:.1f} PB"


def _fmt_elapsed(delta: datetime.timedelta) -> str:
    total = int(delta.total_seconds())
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class WizardPage(Page):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Recovery Wizard page")
        self._ctx = AppContext.instance()
        self._registry = SignatureRegistry.load(custom_dir=self._ctx.config.get("signatures.custom_dir"))
        self._controller = ScanController(self._ctx.db)
        self._queue = RecoveryQueue(self._ctx.db)
        self._detector = DeviceDetector()
        self._pool = WorkerPool()

        self._source: RecoverySource | None = None
        self._selected_sources: list[RecoverySource] = []
        self._scan_id: int | None = None
        self._scan_ids: list[int] = []
        self._pending_scans: set[int] = set()
        self._scan_ui: dict[int, dict] = {}
        self._volumes: list = []
        self._recovered_ok = 0
        self._recovered_failed = 0
        self._pending_quick = False
        self._allowed = 0
        self._scan_mode: str | None = None
        self._recycle_pending_source: RecoverySource | None = None

        self._scan_started: datetime.datetime | None = None
        self._scan_clock = QTimer(self)
        self._scan_clock.setInterval(1000)
        self._scan_clock.timeout.connect(self._update_scan_timer)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(PageHeader("Recovery Wizard", "Guided recovery: device → scan → review → recover → report."))

        content = QHBoxLayout()
        content.setSpacing(16)
        self._step_list = QListWidget()
        self._step_list.setFixedWidth(180)
        for s in STEPS:
            QListWidgetItem(s, self._step_list)
        self._step_list.currentRowChanged.connect(self._on_step_clicked)
        content.addWidget(self._step_list)

        self._stack = QStackedWidget()
        self._build_steps()
        content.addWidget(self._stack, 1)
        root.addLayout(content, 1)

        self._wire_signals()
        self._ctx.events.open_device_requested.connect(self.open_with_source)
        self._go(0)

    # ---------------- step construction ----------------
    def _build_steps(self) -> None:
        self._stack.addWidget(self._build_device_step())
        self._stack.addWidget(self._build_scanmode_step())
        self._stack.addWidget(self._build_scanning_step())
        self._stack.addWidget(self._build_review_step())
        self._stack.addWidget(self._build_complete_step())

    def _build_device_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        heading = QLabel("Choose a recovery source")
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(heading)

        self._vol_list = QListWidget()
        self._vol_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._vol_list.itemSelectionChanged.connect(self._on_volume_selected)
        layout.addWidget(self._vol_list, 1)

        multi_hint = QLabel("Tip: select multiple drives to scan them in parallel (hold Ctrl or Shift).")
        multi_hint.setProperty("faint", True)
        multi_hint.setWordWrap(True)
        layout.addWidget(multi_hint)

        row = QHBoxLayout()
        browse = QPushButton("Load disk image…")
        browse.setObjectName("Ghost")
        browse.clicked.connect(self._browse_image)
        row.addWidget(browse)
        self._image_label = QLabel("")
        self._image_label.setProperty("muted", True)
        row.addWidget(self._image_label, 1)
        layout.addLayout(row)

        folder_row = QHBoxLayout()
        folder_btn = QPushButton("Scan a folder…")
        folder_btn.setObjectName("Ghost")
        folder_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(folder_btn)
        self._folder_label = QLabel("")
        self._folder_label.setProperty("muted", True)
        folder_row.addWidget(self._folder_label, 1)
        layout.addLayout(folder_row)

        self._device_error = QLabel("")
        self._device_error.setStyleSheet("color: #FF4D5E;")
        layout.addWidget(self._device_error)

        nav = QHBoxLayout()
        nav.addStretch(1)
        next_btn = QPushButton("Next")
        next_btn.setObjectName("Primary")
        next_btn.clicked.connect(self._next)
        nav.addWidget(next_btn)
        layout.addLayout(nav)

        return page

    def _build_scanmode_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(14)

        heading = QLabel("Choose a scan method")
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(heading)

        self._mode_group = QButtonGroup(self)
        self._mode_quick = QRadioButton("Quick scan — deleted files via filesystem metadata")
        self._mode_deep = QRadioButton("Deep scan — signature carving across the whole device")
        self._mode_partition = QRadioButton("Partition analysis — MBR/GPT structure and boot sectors")
        for i, radio in enumerate((self._mode_quick, self._mode_deep, self._mode_partition)):
            self._mode_group.addButton(radio, i)
            radio.setProperty("muted", True)
            layout.addWidget(radio)
        self._mode_quick.setChecked(True)

        layout.addSpacing(8)
        self._verify_hash = QCheckBox("Verify recovered files with SHA-256 (slower)")
        layout.addWidget(self._verify_hash)

        workers_row = QHBoxLayout()
        workers_row.addWidget(QLabel("Carve workers:"))
        self._workers = QSpinBox()
        self._workers.setRange(1, 8)
        self._workers.setValue(2)
        workers_row.addWidget(self._workers)
        workers_row.addStretch(1)
        layout.addLayout(workers_row)

        self._mode_error = QLabel("")
        self._mode_error.setStyleSheet("color: #FF4D5E;")
        layout.addWidget(self._mode_error)

        nav = QHBoxLayout()
        back = QPushButton("Back")
        back.setObjectName("Ghost")
        back.clicked.connect(self._back)
        nav.addWidget(back)
        nav.addStretch(1)
        start = QPushButton("Start Scan")
        start.setObjectName("Primary")
        start.clicked.connect(self._start_scan)
        nav.addWidget(start)
        layout.addLayout(nav)

        return page

    def _build_scanning_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(14)

        heading = QLabel("Scanning…")
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(heading)

        self._scan_label = QLabel("Preparing scan…")
        self._scan_label.setProperty("muted", True)
        layout.addWidget(self._scan_label)

        self._scans_box = QVBoxLayout()
        layout.addLayout(self._scans_box)

        self._scan_progress = QProgressBar()
        self._scan_progress.setRange(0, 1000)
        layout.addWidget(self._scan_progress)

        self._scan_found = QLabel("")
        self._scan_found.setProperty("muted", True)
        layout.addWidget(self._scan_found)

        self._scan_timer = QLabel("")
        self._scan_timer.setProperty("muted", True)
        layout.addWidget(self._scan_timer)

        cancel = QPushButton("Cancel scan")
        cancel.setObjectName("Danger")
        cancel.clicked.connect(self._cancel_scan)
        layout.addWidget(cancel, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    def _build_review_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        heading = QLabel("Review recovered candidates")
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(heading)

        scan_row = QHBoxLayout()
        scan_row.addWidget(QLabel("Scan:"))
        self._review_scan_combo = QComboBox()
        self._review_scan_combo.currentIndexChanged.connect(self._on_review_scan_changed)
        scan_row.addWidget(self._review_scan_combo, 1)
        layout.addLayout(scan_row)

        search_row = QHBoxLayout()
        self._review_search = QLineEdit()
        self._review_search.setPlaceholderText("Filter by name, ext:pdf, min:70 …")
        self._review_search.textChanged.connect(self._load_review_rows)
        search_row.addWidget(self._review_search, 1)
        self._review_count = QLabel("")
        self._review_count.setProperty("muted", True)
        search_row.addWidget(self._review_count)
        layout.addLayout(search_row)

        self._folder_hint = QLabel("")
        self._folder_hint.setWordWrap(True)
        self._folder_hint.setProperty("muted", True)
        self._folder_hint.setVisible(False)
        layout.addWidget(self._folder_hint)

        hint_row = QHBoxLayout()
        self._recycle_btn = QPushButton("Scan the Recycle Bin for this drive")
        self._recycle_btn.setObjectName("Ghost")
        self._recycle_btn.clicked.connect(self.start_recycle_scan_for)
        self._recycle_btn.setVisible(False)
        hint_row.addWidget(self._recycle_btn)
        hint_row.addStretch(1)
        layout.addLayout(hint_row)

        self._review_table = QTableWidget(0, 6)
        self._review_table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Quality", "Method", "Status"])
        self._review_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._review_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._review_table.verticalHeader().setVisible(False)
        self._review_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._review_table, 1)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Recover to:"))
        self._vault_combo = QComboBox()
        self._vault_combo.setMinimumWidth(180)
        self._vault_combo.currentIndexChanged.connect(self._on_vault_changed)
        dest_row.addWidget(self._vault_combo)
        self._dest_edit = QLineEdit(os.path.expanduser("~/Recovered Files"))
        dest_row.addWidget(self._dest_edit, 1)
        browse = QPushButton("…")
        browse.setFixedWidth(40)
        browse.clicked.connect(self._browse_dest)
        dest_row.addWidget(browse)
        layout.addLayout(dest_row)

        self._restore_original = QCheckBox(
            "Restore Recycle Bin files to their original locations (uses original folder and name)"
        )
        self._restore_original.setProperty("muted", True)
        layout.addWidget(self._restore_original)

        action_row = QHBoxLayout()
        back = QPushButton("Back")
        back.setObjectName("Ghost")
        back.clicked.connect(self._back)
        action_row.addWidget(back)
        action_row.addStretch(1)
        recover_selected = QPushButton("Recover selected")
        recover_selected.clicked.connect(self.recover_selected)
        action_row.addWidget(recover_selected)
        recover_all = QPushButton("Recover all")
        recover_all.setObjectName("Primary")
        recover_all.clicked.connect(self._recover_all)
        action_row.addWidget(recover_all)
        layout.addLayout(action_row)

        return page

    def _build_complete_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(14)

        heading = QLabel("Complete")
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(heading)

        self._complete_note = QLabel("")
        self._complete_note.setProperty("muted", True)
        self._complete_note.setWordWrap(True)
        layout.addWidget(self._complete_note)

        self._complete_label = QLabel("")
        self._complete_label.setWordWrap(True)
        self._complete_label.setStyleSheet("font-size: 15px;")
        layout.addWidget(self._complete_label)

        self._recovery_progress = QProgressBar()
        self._recovery_progress.setObjectName("Success")
        self._recovery_progress.setRange(0, 1000)
        layout.addWidget(self._recovery_progress)

        report_row = QHBoxLayout()
        report_row.addWidget(QLabel("Generate report:"))
        for name, typ in (("HTML", "html"), ("PDF", "pdf"), ("CSV", "csv")):
            btn = QPushButton(name)
            btn.clicked.connect(lambda _=False, t=typ: self._generate_report(t))
            report_row.addWidget(btn)
        save_session_btn = QPushButton("Save session")
        save_session_btn.setObjectName("Ghost")
        save_session_btn.clicked.connect(self._save_session)
        report_row.addWidget(save_session_btn)
        open_btn = QPushButton("Open output folder")
        open_btn.setObjectName("Ghost")
        open_btn.clicked.connect(self._open_output)
        report_row.addWidget(open_btn)
        report_row.addStretch(1)
        layout.addLayout(report_row)

        new_btn = QPushButton("Start new recovery")
        new_btn.clicked.connect(self.reset)
        layout.addWidget(new_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    # ---------------- signals ----------------
    def _wire_signals(self) -> None:
        self._controller.progress.connect(self._on_scan_progress)
        self._controller.found.connect(self._on_scan_found)
        self._controller.finished.connect(self._on_scan_finished)
        self._controller.cancelled.connect(self._on_scan_cancelled)
        self._controller.failed.connect(self._on_scan_failed)
        self._controller.blocked.connect(self._on_scan_blocked)
        self._queue._signals.item_done.connect(self._on_item_done)
        self._queue._signals.finished.connect(self._on_recovery_finished)

    # ---------------- device step ----------------
    def refresh(self) -> None:
        if self._stack.currentIndex() == 0:
            self._load_volumes()

    def _load_volumes(self) -> None:
        self._vol_list.clear()
        self._vol_list.addItem("Loading drives…")
        self._pool.submit(self._detector.list_volumes, on_done=self._on_volumes, on_error=self._on_device_error)

    def _on_volumes(self, volumes: list) -> None:
        self._vol_list.clear()
        self._volumes = volumes
        for v in volumes:
            label = f"{v.mount_point}  ·  {v.label or 'no label'}  ·  {v.file_system or '?'}  ·  {_human(v.capacity)}"
            QListWidgetItem(label, self._vol_list)
        if getattr(self, "_pending_quick", False):
            self._pending_quick = False
            if volumes:
                self._begin_quick_scan(volumes[0])
            else:
                self._device_error.setText("No volumes available to scan.")

    def start_quick_scan(self) -> None:
        self.reset()
        self._mode_quick.setChecked(True)
        if self._volumes:
            self._begin_quick_scan(self._volumes[0])
        else:
            self._pending_quick = True

    def start_folder_scan(self) -> None:
        """Quick action: pick a folder on a local drive and run a quick scan of it."""
        folder = QFileDialog.getExistingDirectory(self, "Select a folder to scan for deleted files")
        if not folder:
            return
        volume = self._volume_for_path(folder)
        if volume is not None:
            source = RecoverySource(
                kind="volume",
                mount_point=volume.mount_point,
                label=volume.label or "",
                fs_type=volume.file_system or "",
                size=volume.capacity,
                path=folder,
            )
        else:
            drive = os.path.splitdrive(os.path.abspath(folder))[0]
            if not drive or not os.path.isdir(drive + os.sep):
                QMessageBox.warning(
                    self,
                    "Folder not supported",
                    "The selected folder is not on a mounted local drive. "
                    "Choose a folder on a local drive, or use the Recovery Wizard "
                    "to scan a whole volume or a disk image.",
                )
                return
            source = RecoverySource(
                kind="volume",
                mount_point=drive + os.sep,
                label=os.path.basename(folder.rstrip(os.sep)) or drive,
                fs_type="",
                size=0,
                path=folder,
            )
        self.reset()
        self._mode_quick.setChecked(True)
        self._source = source
        self._selected_sources = [source]
        self._folder_label.setText(folder)
        self._start_scan()

    def _begin_quick_scan(self, volume) -> None:
        self._source = RecoverySource(
            kind="volume",
            mount_point=volume.mount_point,
            label=volume.label or "",
            fs_type=volume.file_system or "",
            size=volume.capacity,
        )
        self._selected_sources = [self._source]
        self._verify_hash.setChecked(False)
        self._workers.setValue(2)
        self._start_scan()

    def _on_device_error(self, exc: Exception) -> None:
        self._vol_list.clear()
        self._device_error.setText(f"Could not list drives: {exc}")

    def _on_volume_selected(self) -> None:
        self._device_error.setText("")
        items = self._vol_list.selectedItems()
        if not items:
            return
        sources = []
        for item in items:
            index = self._vol_list.row(item)
            if 0 <= index < len(self._volumes):
                v = self._volumes[index]
                sources.append(
                    RecoverySource(
                        kind="volume",
                        mount_point=v.mount_point,
                        label=v.label or "",
                        fs_type=v.file_system or "",
                        size=v.capacity,
                    )
                )
        if sources:
            self._selected_sources = sources
            self._source = sources[-1]
            self._image_label.setText("")
            self._folder_label.setText("")
            self._device_error.setText("")

    def _browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open disk image", "", "Disk images (*.img *.dd *.iso *.bin *.raw);;All files (*)")
        if not path:
            return
        size = 0
        try:
            size = os.path.getsize(path)
        except OSError:
            pass
        self._source = RecoverySource(kind="image", image_path=path, size=size)
        self._selected_sources = [self._source]
        self._vol_list.clearSelection()
        self._image_label.setText(path)
        self._folder_label.setText("")
        self._device_error.setText("")

    def _volume_for_path(self, path: str):
        try:
            drive = os.path.splitdrive(os.path.abspath(path))[0].upper()
        except (OSError, ValueError):
            return None
        if not drive:
            return None
        for v in self._volumes:
            mp = os.path.splitdrive(os.path.abspath(v.mount_point))[0].upper()
            if mp == drive:
                return v
        return None

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select a folder to scan for deleted files")
        if not folder:
            return
        volume = self._volume_for_path(folder)
        if volume is None:
            self._device_error.setText(
                "The selected folder is not on a volume this app can scan. "
                "Choose a folder on a local drive, or load a disk image instead."
            )
            return
        self._source = RecoverySource(
            kind="volume",
            mount_point=volume.mount_point,
            label=volume.label or "",
            fs_type=volume.file_system or "",
            size=volume.capacity,
            path=folder,
        )
        self._selected_sources = [self._source]
        self._vol_list.clearSelection()
        self._image_label.setText("")
        self._folder_label.setText(folder)
        self._device_error.setText("")

    # ---------------- navigation ----------------
    def _go(self, index: int) -> None:
        index = max(0, min(index, len(STEPS) - 1))
        if index > self._allowed:
            self._allowed = index
        self._step_list.setCurrentRow(index)
        self._stack.setCurrentIndex(index)
        if index == 0:
            self._load_volumes()
        for i in range(len(STEPS)):
            item = self._step_list.item(i)
            if item is None:
                continue
            flags = item.flags()
            if self._step_reachable(i):
                item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
            else:
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)

    def _step_reachable(self, index: int) -> bool:
        if index <= self._allowed:
            return True
        # The Complete step opens once a scan has ended (with or without a
        # completed recovery) so partial results can be wrapped up there.
        return index == 4 and self._allowed >= 3

    def _on_step_clicked(self, row: int) -> None:
        if not self._step_reachable(row):
            return
        self._stack.setCurrentIndex(row)

    def _next(self) -> None:
        step = self._stack.currentIndex()
        if step == 0:
            if not self._selected_sources:
                self._device_error.setText("Select a volume or load an image first.")
                return
            self._go(1)
        elif step == 1:
            self._start_scan()

    def _back(self) -> None:
        self._go(self._stack.currentIndex() - 1)

    # ---------------- scan ----------------
    def _start_scan(self) -> None:
        if not self._selected_sources:
            self._mode_error.setText("Select a device first.")
            return

        if self._mode_quick.isChecked():
            mode = "quick"
        elif self._mode_deep.isChecked():
            mode = "deep"
        else:
            mode = "partition"
        self._scan_mode = mode
        self._scan_ids = []
        self._pending_scans = set()
        self._clear_scan_rows()
        try:
            for source in self._selected_sources:
                config = ScanConfig(
                    mode=mode,
                    source=source,
                    filters={
                        "verify_hashes": self._verify_hash.isChecked(),
                        "deleted_only": mode == "quick",
                    },
                    workers=self._workers.value(),
                )
                scan_id = self._controller.start(config, self._registry)
                self._scan_ids.append(scan_id)
                self._pending_scans.add(scan_id)
                self._add_scan_row(scan_id, source, mode)
                self._ctx.events.scan_started.emit(scan_id)
        except Exception as exc:
            self._mode_error.setText(str(exc))
            return
        self._source = self._selected_sources[-1]
        self._scan_id = self._scan_ids[0]
        count = len(self._scan_ids)
        self._scan_progress.setRange(0, 0)
        self._scan_label.setText(f"Scanning {count} source(s) in parallel…")
        self._scan_found.setText("")
        self._start_scan_clock()
        self._go(2)

    def _start_recycle_scan(self) -> None:
        if self._source is None:
            return
        config = ScanConfig(
            mode="recycle",
            source=self._source,
            filters={},
            workers=0,
        )
        self._scan_mode = "recycle"
        self._scan_ids = []
        self._pending_scans = set()
        self._clear_scan_rows()
        try:
            self._scan_id = self._controller.start(config, self._registry)
            self._scan_ids.append(self._scan_id)
            self._pending_scans.add(self._scan_id)
            self._add_scan_row(self._scan_id, self._source, "recycle")
            self._ctx.events.scan_started.emit(self._scan_id)
        except Exception as exc:
            self._mode_error.setText(str(exc))
            return
        self._scan_progress.setRange(0, 0)
        self._scan_label.setText("Scanning Recycle Bin…")
        self._scan_found.setText("")
        self._start_scan_clock()
        self._go(2)

    def _clear_scan_rows(self) -> None:
        while self._scans_box.count():
            item = self._scans_box.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._scan_ui = {}

    def _add_scan_row(self, scan_id: int, source: RecoverySource, mode: str) -> None:
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 2)
        row_layout.setSpacing(4)

        device = source.display_name if source else "?"
        label = QLabel(f"{device} — {mode}")
        label.setProperty("muted", True)
        row_layout.addWidget(label)

        bar = QProgressBar()
        bar.setRange(0, 1000)
        row_layout.addWidget(bar)

        found = QLabel("")
        found.setProperty("faint", True)
        row_layout.addWidget(found)

        self._scan_ui[scan_id] = {"row": row, "label": label, "bar": bar, "found": found, "found_count": 0}
        self._scans_box.addWidget(row)

    def start_recycle_scan_for(self) -> None:
        """Re-run the last blocked scan against the Recycle Bin instead."""
        if self._recycle_pending_source is None:
            return
        source = self._recycle_pending_source
        self.reset()
        self._source = source
        self._start_recycle_scan()

    def _on_scan_blocked(self, scan_id: int, error: str) -> None:
        self._mark_scan_row_done(scan_id, "blocked")
        device = self._source.display_name if self._source else "device"
        self._ctx.events.scan_blocked.emit(device, error)
        self._recycle_pending_source = self._source
        if len(self._scan_ids) > 1:
            if not self._pending_scans:
                self._stop_scan_clock()
                self._scan_timer.setText("")
                self._scan_progress.setRange(0, 1000)
                self._scan_progress.setValue(0)
                self._scan_label.setText(f"Scans blocked: {error}")
                self._mode_error.setText(
                    "Raw volume access requires administrator privileges — close "
                    "the app and reopen it as administrator to scan these volumes "
                    "directly, or choose the Recycle Bin scan instead."
                )
                self._go(1)
            return
        self._stop_scan_clock()
        self._scan_timer.setText("")
        self._scan_progress.setRange(0, 1000)
        self._scan_progress.setValue(0)
        self._scan_label.setText(f"Scan blocked: {error}")
        answer = QMessageBox.question(
            self,
            "Administrator access required",
            f"The scan of {device} could not start.\n\n{error}\n\n"
            "To scan this volume directly, close Rescuer and reopen it as "
            "administrator.\n\n"
            "Files that were deleted into the Recycle Bin can still be recovered "
            "without administrator rights, and restored to their original locations.\n\n"
            "Scan the Recycle Bin instead?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.when_idle(self._start_recycle_scan)
        else:
            self._abort_scan()

    def _abort_scan(self) -> None:
        self._controller.cancel()
        self._stop_scan_clock()
        self._scan_timer.setText("")
        self._scan_progress.setRange(0, 1000)
        self._scan_progress.setValue(0)
        self._scan_found.setText("")
        self._scan_mode = ""
        self._mode_error.setText(
            "Scan cancelled. Raw volume access requires administrator privileges — "
            "close the app and reopen it as administrator to scan this volume "
            "directly, or choose a different device or scan method."
        )
        self._go(1)

    def _cancel_scan(self) -> None:
        self._controller.cancel()
        self._scan_label.setText("Cancelling…")

    def _start_scan_clock(self) -> None:
        self._scan_started = datetime.datetime.now()
        self._scan_timer.setText("")
        self._scan_clock.start()

    def _update_scan_timer(self) -> None:
        if self._scan_started is None:
            return
        elapsed = datetime.datetime.now() - self._scan_started
        self._scan_timer.setText(f"Elapsed: {_fmt_elapsed(elapsed)}")

    def _stop_scan_clock(self) -> None:
        self._scan_clock.stop()

    def _on_scan_progress(self, scan_id: int, fraction: float, phase: str) -> None:
        self._scan_progress.setRange(0, 0)
        ui = self._scan_ui.get(scan_id)
        if ui is None:
            return
        if self._scan_mode in ("quick", "recycle"):
            ui["bar"].setRange(0, 0)
            if phase:
                ui["label"].setText(f"{ui['label'].text()} — {phase}")
            return
        ui["bar"].setRange(0, 1000)
        ui["bar"].setValue(int(fraction * 1000))
        if phase:
            ui["label"].setText(f"{ui['label'].text()} — {phase}")

    def _on_scan_found(self, scan_id: int, count: int) -> None:
        ui = self._scan_ui.get(scan_id)
        if ui is not None:
            ui["found_count"] = count
            ui["found"].setText(f"{count} candidates found")
        total = sum(u["found_count"] for u in self._scan_ui.values())
        self._scan_found.setText(f"{total} candidates found")

    def _on_scan_finished(self, scan_id: int) -> None:
        self._ctx.events.scan_finished.emit(scan_id)
        self._mark_scan_row_done(scan_id, "finished")
        if self._pending_scans:
            return
        self._scan_label.setText("All scans finished. Loading results…")
        self._go_review(cancelled=False)

    def _on_scan_cancelled(self, _scan_id: int, count: int) -> None:
        self._ctx.events.scan_cancelled.emit(_scan_id, count)
        self._mark_scan_row_done(_scan_id, "cancelled")
        if self._pending_scans:
            return
        self._go_review(cancelled=True)
        self._review_count.setText(
            f"{count} file(s) — scan cancelled, partial results are recoverable"
        )

    def _mark_scan_row_done(self, scan_id: int, text: str) -> None:
        ui = self._scan_ui.get(scan_id)
        if ui is not None:
            ui["label"].setText(f"{ui['label'].text()} — {text}")
            ui["bar"].setRange(0, 1000)
            ui["bar"].setValue(1000)
        self._pending_scans.discard(scan_id)

    def _go_review(self, cancelled: bool = False) -> None:
        self._stop_scan_clock()
        self._update_scan_timer()
        self._scan_progress.setRange(0, 1000)
        self._scan_progress.setValue(1000)
        self._populate_review_combo()
        self._load_review_rows()
        self._load_vaults()
        self._maybe_show_folder_hint()
        self._complete_note.setText(self._scan_summary(cancelled=cancelled))
        self._go(3)

    def _populate_review_combo(self) -> None:
        self._review_scan_combo.blockSignals(True)
        self._review_scan_combo.clear()
        for sid in self._scan_ids:
            row = self._ctx.db.query_one(
                "SELECT device_id, mode FROM scans WHERE id = ?", (sid,)
            )
            mode = row["mode"] if row else "?"
            device = row["device_id"] if row and row["device_id"] else "?"
            self._review_scan_combo.addItem(f"#{sid} · {mode} · {device}", sid)
        if self._scan_ids:
            self._review_scan_combo.setCurrentIndex(len(self._scan_ids) - 1)
        self._review_scan_combo.blockSignals(False)
        self._scan_id = self._review_scan_combo.currentData()

    def _on_review_scan_changed(self) -> None:
        self._scan_id = self._review_scan_combo.currentData()
        self._load_review_rows()
        self._maybe_show_folder_hint()

    def _scan_summary(self, cancelled: bool) -> str:
        total = 0
        for sid in self._scan_ids:
            rows = self._ctx.db.query(
                "SELECT COUNT(*) AS n FROM files WHERE scan_id = ?", (sid,)
            )
            if rows:
                total += rows[0]["n"]
        elapsed = ""
        if self._scan_started is not None:
            elapsed = _fmt_elapsed(datetime.datetime.now() - self._scan_started)
        if cancelled:
            return f"Scan cancelled · {total} partial file(s) found · {elapsed}"
        if len(self._scan_ids) > 1:
            return f"Scan finished · {total} file(s) found across {len(self._scan_ids)} source(s) · {elapsed}"
        return f"Scan finished · {total} file(s) found · {elapsed}"

    def _maybe_show_folder_hint(self) -> None:
        """Explain zero quick-scan results and offer the Recycle Bin scan."""
        self._folder_hint.setVisible(False)
        self._recycle_btn.setVisible(False)
        if self._scan_mode != "quick" or self._scan_id is None:
            return
        source = self._source
        if source is None or source.kind != "volume":
            return
        rows = self._ctx.db.query(
            "SELECT COUNT(*) AS n FROM files WHERE scan_id = ?", (self._scan_id,)
        )
        if rows and rows[0]["n"] != 0:
            return
        target = source.path or source.display_name
        self._recycle_pending_source = source
        self._folder_hint.setText(
            f"No deleted files found in {target}.\n\n"
            "Files deleted with the Delete key are moved to the Windows "
            "Recycle Bin rather than removed from the folder, so they do not "
            "appear here. Use the Recycle Bin scan to recover them and restore "
            "them to their original locations."
        )
        self._folder_hint.setVisible(True)
        self._recycle_btn.setVisible(True)

    def _on_scan_failed(self, scan_id: int, error: str) -> None:
        self._ctx.events.scan_error.emit(scan_id, error)
        ui = self._scan_ui.get(scan_id)
        if ui is not None:
            ui["label"].setText(f"{ui['label'].text()} — failed: {error}")
            ui["bar"].setRange(0, 1000)
            ui["bar"].setValue(0)
        self._pending_scans.discard(scan_id)
        if self._pending_scans:
            return
        any_ok = False
        for sid in self._scan_ids:
            rows = self._ctx.db.query(
                "SELECT COUNT(*) AS n FROM files WHERE scan_id = ?", (sid,)
            )
            if rows and rows[0]["n"]:
                any_ok = True
        if any_ok:
            self._scan_label.setText("Some scans failed; showing the results that were found.")
            self._go_review(cancelled=False)
        else:
            self._stop_scan_clock()
            self._scan_progress.setRange(0, 1000)
            self._scan_progress.setValue(0)
            self._scan_label.setText(f"Scan failed: {error}")
            self._mode_error.setText(str(error))
            self._go(1)

    # ---------------- review ----------------
    def _load_review_rows(self) -> None:
        if self._scan_id is None:
            return
        from rescuer.engine.search.engine import FileSearch

        search = FileSearch(self._ctx.db)
        text = self._review_search.text()
        rows = search.search(scan_id=self._scan_id, text=text, limit=2000)
        self._review_count.setText(f"{len(rows)} file(s)")
        self._review_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            name_item = QTableWidgetItem(row["name"] or "Untitled")
            name_item.setData(Qt.ItemDataRole.UserRole, row["id"])
            self._review_table.setItem(r, 0, name_item)
            self._review_table.setItem(r, 1, QTableWidgetItem((row["ext"] or "").lstrip(".").upper()))
            self._review_table.setItem(r, 2, QTableWidgetItem(_human(row["size"] or 0)))
            stars = StarsLabel(stars_from_score(row["quality_score"] or 0), row["quality_score"])
            self._review_table.setCellWidget(r, 3, stars)
            self._review_table.setItem(r, 4, QTableWidgetItem("Carved" if row["found_by"] == "signature" else row["found_by"] or "FS"))
            self._review_table.setItem(r, 5, QTableWidgetItem(row["status"] or "new"))
        self._review_table.resizeColumnsToContents()

    def _selected_file_ids(self) -> list[int]:
        ids = []
        for item in self._review_table.selectedItems():
            if item.column() == 0:
                fid = item.data(Qt.ItemDataRole.UserRole)
                if fid is not None:
                    ids.append(fid)
        return ids

    def _browse_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose recovery destination", self._dest_edit.text())
        if path:
            self._dest_edit.setText(path)

    def _load_vaults(self) -> None:
        from rescuer.engine.vault import manager as vault_manager
        self._vault_combo.blockSignals(True)
        self._vault_combo.clear()
        self._vault_combo.addItem("Custom folder…", "")
        vaults = vault_manager.list_vaults(self._ctx.db)
        for v in vaults:
            self._vault_combo.addItem(v.get("folder", ""), v.get("id"))
        self._vault_combo.blockSignals(False)

    def _on_vault_changed(self) -> None:
        data = self._vault_combo.currentData()
        if data:
            vault = self._vault_combo.currentText()
            self._dest_edit.setText(vault)
        else:
            self._dest_edit.setText(os.path.expanduser("~/Recovered Files"))

    def _start_recovery(self, file_ids: list[int]) -> None:
        from rescuer.engine.recovery.queue import enqueue

        if not file_ids or self._scan_id is None:
            return
        enqueue(self._ctx.db, file_ids)
        self._recovered_ok = 0
        self._recovered_failed = 0
        self._recovery_progress.setValue(0)
        self._restoring = self._restore_original.isChecked()
        self._complete_label.setText(f"Recovering {len(file_ids)} file(s)…")
        self._queue.start(self._scan_id, self._dest_edit.text(), self._registry,
                          verify_hash=self._verify_hash.isChecked(),
                          restore_original=self._restoring)
        self._go(4)

    def recover_selected(self) -> None:
        ids = self._selected_file_ids()
        if not ids:
            self._review_table.selectAll()
            ids = self._selected_file_ids()
        self._start_recovery(ids)

    def _recover_all(self) -> None:
        ids = []
        for row in range(self._review_table.rowCount()):
            item = self._review_table.item(row, 0)
            if item is not None:
                fid = item.data(Qt.ItemDataRole.UserRole)
                if fid is not None:
                    ids.append(fid)
        self._start_recovery(ids)

    def _on_item_done(self, outcome) -> None:
        if outcome.ok:
            self._recovered_ok += 1
        else:
            self._recovered_failed += 1
        total = self._recovered_ok + self._recovered_failed
        self._complete_label.setText(
            f"Recovered {self._recovered_ok} file(s), {self._recovered_failed} failed."
        )
        self._recovery_progress.setValue(0 if total == 0 else int(self._recovered_ok / total * 1000))

    def _on_recovery_finished(self, done: int, failed: int) -> None:
        self._recovered_ok = done
        self._recovered_failed = failed
        if getattr(self, "_restoring", False):
            self._complete_label.setText(
                f"Finished: {done} file(s) restored to their original locations, "
                f"{failed} failed."
            )
        else:
            self._complete_label.setText(
                f"Finished: {done} file(s) recovered, {failed} failed. Output in:\n{self._dest_edit.text()}"
            )
        self._recovery_progress.setValue(1000)

    # ---------------- complete ----------------
    def _generate_report(self, report_type: str) -> None:
        if self._scan_id is None:
            return
        from rescuer.engine.reports.generator import generate

        out = self._dest_edit.text()
        try:
            path = generate(self._ctx.db, self._scan_id, out, report_type)
        except Exception as exc:
            self._complete_label.setText(f"Report failed: {exc}")
            return
        self._complete_label.setText(f"Report saved:\n{path}")

    def _save_session(self) -> None:
        from rescuer.engine.session import manager as sessions
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Save session", "Session name:")
        if not ok or not name.strip():
            return
        sessions.create_session(self._ctx.db, name.strip(), self._scan_id)
        QMessageBox.information(self, "Session saved", f"Session \"{name.strip()}\" saved.")

    def _open_output(self) -> None:
        path = self._dest_edit.text()
        if os.path.isdir(path):
            os.startfile(path)

    # ---------------- external entry ----------------
    def open_with_source(self, source: RecoverySource) -> None:
        self.reset()
        self._source = source
        self._selected_sources = [source]
        self._go(1)
        if source.kind == "image":
            self._image_label.setText(source.image_path)

    def reset(self) -> None:
        self._source = None
        self._selected_sources = []
        self._scan_id = None
        self._scan_ids = []
        self._pending_scans = set()
        self._clear_scan_rows()
        self._pending_quick = False
        self._allowed = 0
        self._scan_mode = None
        self._recycle_pending_source = None
        self._restoring = False
        self._stop_scan_clock()
        self._scan_started = None
        self._scan_timer.setText("")
        self._complete_note.setText("")
        self._folder_hint.setVisible(False)
        self._recycle_btn.setVisible(False)
        self._scan_progress.setValue(0)
        self._review_table.setRowCount(0)
        self._image_label.setText("")
        self._folder_label.setText("")
        self._vol_list.clearSelection()
        self._recovered_ok = 0
        self._recovered_failed = 0
        self._review_scan_combo.blockSignals(True)
        self._review_scan_combo.clear()
        self._review_scan_combo.blockSignals(False)
        self._go(0)


def stars_from_score(score: int) -> int:
    if score >= 90:
        return 5
    if score >= 75:
        return 4
    if score >= 50:
        return 3
    if score >= 25:
        return 2
    return 1
