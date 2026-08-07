from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from rescuer.ui.pages.base import Page, PageHeader


class StatCard(QFrame):
    def __init__(self, title: str, value: str = "", subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(6)

        self.value_label = QLabel(value or "—")
        self.value_label.setStyleSheet("font-size: 28px; font-weight: 700;")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.value_label)

        title_label = QLabel(title)
        title_label.setProperty("muted", True)
        title_label.setStyleSheet("font-size: 12px; font-weight: 600; letter-spacing: 0.4px;")
        layout.addWidget(title_label)

        self.sub_label = QLabel(subtitle)
        self.sub_label.setProperty("faint", True)
        self.sub_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.sub_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_subtitle(self, subtitle: str) -> None:
        self.sub_label.setText(subtitle)


class EmptyState(QFrame):
    def __init__(self, title: str, message: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 40, 32, 40)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(title_label)

        if message:
            msg = QLabel(message)
            msg.setProperty("muted", True)
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setWordWrap(True)
            layout.addWidget(msg)
