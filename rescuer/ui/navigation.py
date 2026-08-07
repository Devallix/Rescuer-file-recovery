from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from rescuer import APP_NAME, APP_TAGLINE, __version__
from rescuer.core.theme import get_palette
from rescuer.paths import Paths
from rescuer.ui.resources.icons import icon


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon_name: str
    shortcut: str | None = None


class NavButton(QPushButton):
    clicked_key = Signal(str)

    def __init__(self, item: NavItem, palette) -> None:
        super().__init__(item.label)
        self._item = item
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("navButton", True)
        self.setIcon(icon(item.icon_name, palette.text_muted, 48))
        self.setIconSize(QSize(18, 18))
        self.setToolTip(f"{item.label} ({item.shortcut})" if item.shortcut else item.label)
        self.setFixedHeight(44)
        self.clicked.connect(lambda: self.clicked_key.emit(self._item.key))
        self.update_theme(palette)

    def update_theme(self, palette) -> None:
        color = palette.accent if self.isChecked() else palette.text_muted
        self.setIcon(icon(self._item.icon_name, color, 48))


class NavRail(QFrame):
    navigate = Signal(str)

    def __init__(self, items: list[NavItem], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("NavRail")
        self.setFixedWidth(216)
        self._items = items
        self._buttons: dict[str, NavButton] = {}
        self._palette = get_palette("dark")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(4)

        brand = QLabel(f"<b>{APP_NAME}</b>")
        brand.setStyleSheet("font-size: 17px; letter-spacing: 0.3px; padding: 4px 10px;")
        layout.addWidget(brand)

        subtitle = QLabel(APP_TAGLINE)
        subtitle.setProperty("muted", True)
        subtitle.setStyleSheet("font-size: 10.5px; padding: 0 10px 10px 10px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        for item in items:
            btn = NavButton(item, self._palette)
            btn.clicked_key.connect(self._on_clicked)
            layout.addWidget(btn)
            self._buttons[item.key] = btn

        layout.addStretch(1)

        footer_image = QLabel()
        footer_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_pix = QPixmap(str(Paths.img_dir / "rescuer.png"))
        if not footer_pix.isNull():
            footer_pix = footer_pix.scaled(
                132, 124,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            footer_image.setPixmap(footer_pix)
        layout.addWidget(footer_image)

        version = QLabel(f"v{__version__}")
        version.setProperty("faint", True)
        version.setStyleSheet("font-size: 10px; padding: 0 10px;")
        layout.addWidget(version)

    def _on_clicked(self, key: str) -> None:
        for k, btn in self._buttons.items():
            btn.setChecked(k == key)
            btn.update_theme(self._palette)
        self.navigate.emit(key)

    def select(self, key: str) -> None:
        self._on_clicked(key)

    def set_palette(self, palette) -> None:
        self._palette = palette
        for btn in self._buttons.values():
            btn.update_theme(palette)
