from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import QBuffer, QByteArray, Qt, QIODevice
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPainter


def _svg(color: str, paths: str, viewbox: str = "0 0 24 24", fill_rule: str = "nonzero") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}" '
        f'fill="{color}" fill-rule="{fill_rule}">'
        f"<path d=\"{paths}\"/></svg>"
    )


ICON_PATHS = {
    "dashboard": "M3 3h8v8H3V3zm10 0h8v5h-8V3zm0 7h8v11h-8V10zM3 13h8v8H3v-8z",
    "drives": "M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm2 4v3h4V8H7zm7 0v3h3V8h-3zm-7 6v3h4v-3H7zm7 0v3h3v-3h-3z",
    "wizard": "M9.5 2l1.2 3.3L14 6.5l-3.3 1.2L9.5 11l-1.2-3.3L5 6.5l3.3-1.2L9.5 2zM19 9l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9.9-2.4zM12 12l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7.7-1.9z",
    "results": "M10 2a8 8 0 1 0 4.9 14.32l5.4 5.39 1.4-1.42-5.38-5.4A8 8 0 0 0 10 2zm0 2a6 6 0 1 1 0 12 6 6 0 0 1 0-12z",
    "queue": "M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h10v2H4v-2zm14-1.6v6l4.5-3-4.5-3z",
    "reports": "M6 2h8l6 6v14H6V2zm7 1.5V9h5.5L13 3.5zM8 12h9v2H8v-2zm0 4h9v2H8v-2z",
    "settings": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm9 4c0-.6-.1-1.1-.2-1.6l2-1.5-2-3.4-2.3 1a7 7 0 0 0-2.7-1.6L15.5 2h-7l-.4 2.9a7 7 0 0 0-2.7 1.6l-2.3-1-2 3.4 2 1.5c-.1.5-.2 1-.2 1.6s.1 1.1.2 1.6l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 2.7 1.6L8.5 22h7l.4-2.9a7 7 0 0 0 2.7-1.6l2.3 1 2-3.4-2-1.5c.1-.5.2-1 .2-1.6z",
    "plugins": "M4 4h4v4H4V4zm6 0h4v4h-4V4zm6 0h4v4h-4V4zM4 10h4v4H4v-4zm6 0h4v4h-4v-4zm6 0h4v4h-4v-4zM4 16h4v4H4v-4zm6 0h4v4h-4v-4zm6 0h4v4h-4v-4z",
    "sessions": "M17 3H7c-1.1 0-2 .9-2 2v16l7-3 7 3V5c0-1.1-.9-2-2-2z",
    "vault": "M12 1a5 5 0 0 0-5 5v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2h-1V6a5 5 0 0 0-5-5zm3 7a3 3 0 0 1 3 3v1h-1V8a1 1 0 0 0-2 0v7H8v-2a3 3 0 0 1 3-3h4z",
}


def icon(name: str, color: str, size: int = 48) -> QIcon:
    svg = _svg(color, ICON_PATHS[name])
    renderer = QSvgRenderer()
    renderer.load(svg.encode("utf-8"))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    icon_ = QIcon(pm)
    icon_.addPixmap(pm, QIcon.Mode.Normal)
    return icon_
