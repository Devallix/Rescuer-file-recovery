from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rescuer.core.app_context import AppContext
from rescuer.engine.models import RecoverySource
from rescuer.engine.recovery.queue import source_from_scan as _source_from_scan
from rescuer.engine.search.engine import FileSearch
from rescuer.engine.search.assistant import SmartAssistant
from rescuer.engine.signatures.registry import SignatureRegistry
from rescuer.ui.pages.base import Page, PageHeader
from rescuer.ui.widgets.preview import PreviewPanel
from rescuer.ui.widgets.stars import StarsLabel


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


class ResultsPage(Page):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Results Explorer page")
        self._ctx = AppContext.instance()
        self._registry = SignatureRegistry.load(custom_dir=self._ctx.config.get("signatures.custom_dir"))
        self._search = FileSearch(self._ctx.db)
        self._assistant = SmartAssistant(self._search)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(PageHeader("Results Explorer", "Search and preview everything found across scans."))

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Scan:"))
        self._scan_combo = QComboBox()
        self._scan_combo.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self._scan_combo)
        toolbar.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Try “deleted photos”, name:report, ext:pdf, min:80 …")
        self._search_edit.textChanged.connect(self._apply_filters)
        toolbar.addWidget(self._search_edit, 1)
        toolbar.addWidget(QLabel("Min score:"))
        self._min_score = QSpinBox()
        self._min_score.setRange(0, 100)
        self._min_score.setValue(0)
        self._min_score.valueChanged.connect(self._apply_filters)
        toolbar.addWidget(self._min_score)
        toolbar.addWidget(QLabel("Min size (KB):"))
        self._min_size = QSpinBox()
        self._min_size.setRange(0, 999999)
        self._min_size.setValue(0)
        self._min_size.valueChanged.connect(self._apply_filters)
        toolbar.addWidget(self._min_size)
        toolbar.addWidget(QLabel("Max size (KB):"))
        self._max_size = QSpinBox()
        self._max_size.setRange(0, 999999)
        self._max_size.setValue(0)
        self._max_size.valueChanged.connect(self._apply_filters)
        toolbar.addWidget(self._max_size)
        self._deleted_only = QCheckBox("Deleted only")
        self._deleted_only.toggled.connect(self._apply_filters)
        toolbar.addWidget(self._deleted_only)
        self._duplicates_only = QCheckBox("Duplicates only")
        self._duplicates_only.toggled.connect(self._apply_filters)
        toolbar.addWidget(self._duplicates_only)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Quality", "Confidence", "Method", "Status"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self._table)

        self._preview = PreviewPanel()
        self._preview.setMinimumWidth(320)
        splitter.addWidget(self._preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        action_row = QHBoxLayout()
        self._count_label = QLabel("")
        self._count_label.setProperty("muted", True)
        action_row.addWidget(self._count_label)
        action_row.addStretch(1)
        export_btn = QPushButton("Export CSV")
        export_btn.setObjectName("Ghost")
        export_btn.clicked.connect(self._export_csv)
        action_row.addWidget(export_btn)
        recover = QPushButton("Recover selected")
        recover.setObjectName("Primary")
        recover.clicked.connect(self._recover_selected)
        action_row.addWidget(recover)
        new_scan = QPushButton("New scan")
        new_scan.setObjectName("Ghost")
        new_scan.clicked.connect(self._open_wizard)
        action_row.addWidget(new_scan)
        root.addLayout(action_row)

    def refresh(self) -> None:
        self._load_scans()
        self._apply_filters()

    def _load_scans(self) -> None:
        current = self._scan_combo.currentData()
        self._scan_combo.blockSignals(True)
        self._scan_combo.clear()
        rows = self._ctx.db.query(
            "SELECT id, device_id, mode, started_at, found_count FROM scans ORDER BY id DESC"
        )
        for r in rows:
            label = f"#{r['id']} · {r['mode']} · {r['device_id'] or '?'} · {r['started_at'] or ''}"
            self._scan_combo.addItem(label, r["id"])
        if current is not None:
            idx = self._scan_combo.findData(current)
            if idx >= 0:
                self._scan_combo.setCurrentIndex(idx)
        self._scan_combo.blockSignals(False)

    def _apply_filters(self) -> None:
        scan_id = self._scan_combo.currentData()
        if scan_id is None:
            self._table.setRowCount(0)
            self._count_label.setText("No scans yet.")
            return
        rows = self._search.search(
            text=self._search_edit.text(),
            scan_id=scan_id,
            deleted=True if self._deleted_only.isChecked() else None,
            min_score=self._min_score.value(),
            min_size=self._min_size.value(),
            max_size=self._max_size.value() if self._max_size.value() > 0 else None,
            limit=2000,
        )
        if self._duplicates_only.isChecked():
            seen = {}
            dup_ids = set()
            for row in rows:
                h = row.get("sha256")
                if h:
                    if h in seen:
                        dup_ids.add(seen[h])
                        dup_ids.add(row["id"])
                    else:
                        seen[h] = row["id"]
            rows = [r for r in rows if r["id"] in dup_ids]
        self._count_label.setText(f"{len(rows)} result(s)")
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            name_item = QTableWidgetItem(row["name"] or "Untitled")
            name_item.setData(Qt.ItemDataRole.UserRole, row["id"])
            name_item.setData(Qt.ItemDataRole.UserRole + 1, row["found_by"])
            self._table.setItem(r, 0, name_item)
            self._table.setItem(r, 1, QTableWidgetItem((row["ext"] or "").lstrip(".").upper()))
            self._table.setItem(r, 2, QTableWidgetItem(_human(row["size"] or 0)))
            stars = StarsLabel(stars_from_score(row["quality_score"] or 0), row["quality_score"])
            self._table.setCellWidget(r, 3, stars)
            self._table.setItem(r, 4, QTableWidgetItem(f"{row['confidence'] or 0}%"))
            self._table.setItem(r, 5, QTableWidgetItem("Carved" if row["found_by"] == "signature" else (row["found_by"] or "FS")))
            self._table.setItem(r, 6, QTableWidgetItem(row["status"] or "new"))
        self._preview.clear()

    def _on_double_click(self, item: QTableWidgetItem) -> None:
        fid = item.data(Qt.ItemDataRole.UserRole)
        if fid is None:
            return
        row = self._ctx.db.query_one("SELECT * FROM files WHERE id = ?", (fid,))
        if row is None:
            return
        from rescuer.engine.recovery.queue import found_from_row
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QTextEdit

        found = found_from_row(row, None)
        dlg = QDialog(self)
        dlg.setWindowTitle(found.name or "File details")
        dlg.setMinimumWidth(400)
        layout = QFormLayout(dlg)
        layout.setSpacing(8)
        fields = [
            ("Name", found.name),
            ("Size", _human(found.size)),
            ("Extension", found.ext),
            ("Path", found.path),
            ("Found by", found.found_by),
            ("Deleted", "Yes" if found.is_deleted else "No"),
            ("Created", found.created or "—"),
            ("Modified", found.modified or "—"),
            ("Deleted at", found.deleted_at or "—"),
            ("Inode", str(found.inode) if found.inode else "—"),
            ("Cluster", str(found.cluster) if found.cluster else "—"),
            ("Raw offset", str(found.raw_offset) if found.raw_offset is not None else "—"),
            ("Quality", f"{found.score}/100" if found.score is not None else "—"),
            ("Confidence", f"{found.confidence}%" if found.confidence is not None else "—"),
            ("SHA-256", found.sha256 or "—"),
        ]
        for label_text, value in fields:
            layout.addRow(QLabel(f"<b>{label_text}</b>"), QLabel(str(value) if value is not None else "—"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)
        dlg.exec()

    def _on_context_menu(self, pos) -> None:
        items = self._table.selectedItems()
        if not items:
            return
        fid = items[0].data(Qt.ItemDataRole.UserRole)
        if fid is None:
            return
        row = self._ctx.db.query_one("SELECT path, name FROM files WHERE id = ?", (fid,))
        if row is None:
            return
        menu = QMenu(self)
        copy_path = menu.addAction("Copy path")
        copy_name = menu.addAction("Copy filename")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == copy_path:
            cb = QGuiApplication.clipboard()
            cb.setText(row.get("path") or row.get("name") or "")
        elif action == copy_name:
            cb = QGuiApplication.clipboard()
            cb.setText(row.get("name") or "")

    def _on_selection_changed(self) -> None:
        items = self._table.selectedItems()
        if not items:
            return
        fid = items[0].data(Qt.ItemDataRole.UserRole)
        if fid is None:
            return
        row = self._ctx.db.query_one("SELECT * FROM files WHERE id = ?", (fid,))
        if row is None:
            return
        from rescuer.engine.recovery.queue import found_from_row

        found = found_from_row(row, None)
        source = self._source_for_scan()
        self._preview.show_file(found, source, self._registry)

    def _source_for_scan(self) -> RecoverySource | None:
        scan_id = self._scan_combo.currentData()
        if scan_id is None:
            return None
        return _source_from_scan(self._ctx.db, scan_id)

    def _selected_ids(self) -> list[int]:
        ids = []
        for item in self._table.selectedItems():
            if item.column() == 0:
                fid = item.data(Qt.ItemDataRole.UserRole)
                if fid is not None:
                    ids.append(fid)
        return ids

    def _recover_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        from rescuer.engine.recovery.queue import enqueue

        added = enqueue(self._ctx.db, ids)
        self._ctx.events.files_recovered.emit(ids)
        self._count_label.setText(f"Queued {added} file(s) for recovery. Open the Recovery Queue to start.")
        self.refresh()

    def _export_csv(self) -> None:
        import csv
        import os
        from datetime import date

        scan_id = self._scan_combo.currentData()
        if scan_id is None:
            return
        rows = self._search.search(
            text=self._search_edit.text(),
            scan_id=scan_id,
            deleted=True if self._deleted_only.isChecked() else None,
            min_score=self._min_score.value(),
            limit=5000,
        )
        if not rows:
            self._count_label.setText("Nothing to export.")
            return
        default_dir = os.path.expanduser("~/Documents")
        os.makedirs(default_dir, exist_ok=True)
        path = os.path.join(default_dir, f"rescuer_scan_{scan_id}_{date.today().isoformat()}.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        self._count_label.setText(f"Exported {len(rows)} rows to {path}")

    def _open_wizard(self) -> None:
        self._ctx.events.open_device_requested.emit(None)


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
