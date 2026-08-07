import datetime
import os

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from rescuer.core.app_context import AppContext
from rescuer.engine.reports.generator import generate
from rescuer.ui.pages.base import Page, PageHeader


class ReportsPage(Page):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Reports page")
        self._ctx = AppContext.instance()

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(PageHeader("Reports", "Professional, shareable recovery reports (HTML, PDF, CSV)."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Scan:"))
        self._scan_combo = QComboBox()
        row.addWidget(self._scan_combo)
        row.addWidget(QLabel("Format:"))
        self._format_combo = QComboBox()
        self._format_combo.addItems(["HTML", "PDF", "CSV"])
        row.addWidget(self._format_combo)
        row.addWidget(QLabel("Folder:"))
        self._folder_edit = QLabel(self._default_folder())
        self._folder_edit.setProperty("muted", True)
        row.addWidget(self._folder_edit, 1)
        browse = QPushButton("…")
        browse.setFixedWidth(40)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        generate_btn = QPushButton("Generate")
        generate_btn.setObjectName("Primary")
        generate_btn.clicked.connect(self._generate)
        row.addWidget(generate_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("Danger")
        clear_btn.clicked.connect(self._clear_reports)
        row.addWidget(clear_btn)
        root.addLayout(row)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Scan", "Type", "Path", "Generated"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.itemDoubleClicked.connect(lambda item: self._open(item))
        root.addWidget(self._table, 1)

        hint = QLabel("Tip: double-click a report row to open it. Reports are also saved to the reports folder.")
        hint.setProperty("muted", True)
        root.addWidget(hint)

    @staticmethod
    def _default_folder() -> str:
        from rescuer.paths import Paths

        Paths.ensure_dirs()
        return str(Paths.reports_dir)

    def refresh(self) -> None:
        current = self._scan_combo.currentData()
        self._scan_combo.blockSignals(True)
        self._scan_combo.clear()
        rows = self._ctx.db.query("SELECT id, mode, device_id FROM scans ORDER BY id DESC")
        for r in rows:
            self._scan_combo.addItem(f"#{r['id']} · {r['mode']} · {r['device_id'] or '?'}", r["id"])
        if current is not None:
            idx = self._scan_combo.findData(current)
            if idx >= 0:
                self._scan_combo.setCurrentIndex(idx)
        self._scan_combo.blockSignals(False)
        self._load_table()

    def _load_table(self) -> None:
        rows = self._ctx.db.query("SELECT * FROM reports ORDER BY generated_at DESC")
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._table.setItem(r, 0, QTableWidgetItem(f"#{row['scan_id']}"))
            self._table.setItem(r, 1, QTableWidgetItem(row["report_type"]))
            self._table.setItem(r, 2, QTableWidgetItem(row["path"]))
            self._table.setItem(r, 3, QTableWidgetItem(row["generated_at"] or ""))

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose reports folder", self._folder_edit.text())
        if path:
            self._folder_edit.setText(path)

    def _generate(self) -> None:
        scan_id = self._scan_combo.currentData()
        if scan_id is None:
            return
        report_type = self._format_combo.currentText().lower()
        folder = self._folder_edit.text()
        try:
            path = generate(self._ctx.db, scan_id, folder, report_type)
        except Exception as exc:
            self._load_table()
            return
        self._ctx.db.execute(
            "INSERT INTO reports (scan_id, report_type, path, generated_at) VALUES (?, ?, ?, ?)",
            (scan_id, report_type, path, datetime.datetime.now().isoformat(sep=" ", timespec="seconds")),
        )
        self._load_table()

    def _open(self, item: QTableWidgetItem) -> None:
        if item.column() != 2:
            return
        path = item.text()
        if path and os.path.exists(path):
            os.startfile(path)

    def _clear_reports(self) -> None:
        rows = self._ctx.db.query("SELECT id, path FROM reports")
        if not rows:
            return
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "Clear reports",
            f"Delete all {len(rows)} report(s) from the list? The report files on disk will also be removed.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for row in rows:
            path = row["path"]
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self._ctx.db.execute("DELETE FROM reports")
        self._load_table()
