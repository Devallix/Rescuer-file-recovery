from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from rescuer.core.worker_pool import WorkerPool
from rescuer.engine.models import FoundFile, RecoverySource
from rescuer.engine.preview import build_preview_package
from rescuer.engine.signatures.registry import SignatureRegistry


class PreviewPanel(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._pool = WorkerPool()
        self._job = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._header = QLabel("Preview")
        self._header.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._header)

        self._stack = QWidget()
        self._stack_layout = QVBoxLayout(self._stack)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)

        self._empty = QLabel("Select a file to preview it.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setProperty("muted", True)
        self._empty.setWordWrap(True)
        self._stack_layout.addWidget(self._empty)
        layout.addWidget(self._stack, 1)

    def clear(self) -> None:
        self._job += 1
        self._header.setText("Preview")
        self._show_placeholder("Select a file to preview it.")

    def show_file(self, found: FoundFile, source: RecoverySource | None, registry: SignatureRegistry | None) -> None:
        self._job += 1
        job = self._job
        self._header.setText(found.name or "Untitled")
        self._show_placeholder("Generating preview…")
        self._pool.submit(
            build_preview_package,
            found,
            source,
            registry,
            on_done=lambda result: self._on_ready(job, found, result),
            on_error=lambda _exc: self._on_error(job),
        )

    def _show_placeholder(self, text: str) -> None:
        while self._stack_layout.count():
            item = self._stack_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("muted", True)
        label.setWordWrap(True)
        self._stack_layout.addWidget(label)

    def _on_ready(self, job: int, found: FoundFile, result: dict) -> None:
        if job != self._job:
            return
        while self._stack_layout.count():
            item = self._stack_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        thumb = result.get("thumbnail")
        text = result.get("text")
        kind = result.get("kind", "binary")

        if thumb and Path(thumb).exists():
            pixmap = QPixmap(thumb)
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setPixmap(pixmap.scaled(
                max(self.width() - 24, 120), 420,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            self._stack_layout.addWidget(label)
        elif text:
            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            editor.setPlainText(text)
            editor.setStyleSheet("border: none;")
            self._stack_layout.addWidget(editor)
        else:
            placeholder = QLabel(
                f"No visual preview available for this {kind} file.\n"
                "It can still be recovered from the source."
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setProperty("muted", True)
            placeholder.setWordWrap(True)
            self._stack_layout.addWidget(placeholder)

    def _on_error(self, job: int) -> None:
        if job != self._job:
            return
        self._show_placeholder("Preview could not be generated.")
