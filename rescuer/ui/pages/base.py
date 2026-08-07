from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class Page(QWidget):
    def refresh(self) -> None:
        pass

    def on_theme_changed(self, palette) -> None:
        pass


class PageHeader(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PageHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 18)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 26px; font-weight: 700;")
        layout.addWidget(title_label)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setProperty("muted", True)
            sub.setStyleSheet("font-size: 13px;")
            layout.addWidget(sub)

    def set_heading(self, title: str, subtitle: str = "") -> None:
        pass


class Card(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
