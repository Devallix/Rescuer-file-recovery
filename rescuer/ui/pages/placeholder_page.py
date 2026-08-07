from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout

from rescuer.ui.pages.base import Page, PageHeader
from rescuer.ui.widgets.cards import EmptyState


class PlaceholderPage(Page):
    def __init__(self, title: str, description: str, phase: str, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(PageHeader(title, description))
        state = EmptyState(
            "Coming soon",
            f"This module is part of {phase} and is not implemented yet. "
            "It will land in a future development phase of Rescuer.",
        )
        root.addWidget(state)
        root.addStretch(1)
