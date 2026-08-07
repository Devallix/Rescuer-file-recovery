from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from rescuer.core.theme import get_palette


class RingWidget(QWidget):
    def __init__(self, parent=None, radius: float = 0.0) -> None:
        super().__init__(parent)
        self._radius = radius
        self._value = 0.0
        self._value_color: str | None = None
        self._title = ""
        self._subtitle = ""
        self.setMinimumSize(120, 120)

    def set_value(self, value: float, color: str | None = None) -> None:
        self._value = max(0.0, min(1.0, value))
        if color:
            self._value_color = color
        self.update()

    def set_title(self, title: str) -> None:
        self._title = title
        self.update()

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle = subtitle
        self.update()

    def paintEvent(self, event) -> None:
        palette = get_palette("dark")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height())
        thickness = max(10.0, side * 0.1)
        margin = 8.0
        rect = QRectF(margin, margin, side - 2 * margin, side - 2 * margin)

        painter.setPen(QPen(QColor(palette.surface_alt), thickness))
        painter.drawArc(rect, 0, 360 * 16)

        color = QColor(self._value_color or palette.emerald)
        span = int(-360 * 16 * self._value)
        painter.setPen(QPen(color, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90 * 16, span)

        inner = rect.adjusted(thickness, thickness, -thickness, -thickness)
        inner_rect = inner.adjusted(2, 2, -2, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.surface))
        painter.drawEllipse(inner)

        if self._value_color and palette.name == "dark":
            label_color = self._value_color
        else:
            label_color = palette.text
        painter.setPen(QColor(label_color))
        percent_font = QFont("Segoe UI", max(16, int(side * 0.16)), QFont.Weight.DemiBold)
        painter.setFont(percent_font)
        percent = f"{self._value * 100:.0f}%"
        fm = QFontMetrics(percent_font)
        painter.drawText(
            inner_rect,
            Qt.AlignmentFlag.AlignCenter,
            percent,
        )

        if self._title:
            title_font = QFont("Segoe UI", max(8, int(side * 0.075)))
            painter.setFont(title_font)
            painter.setPen(QColor(palette.text_muted))
            fm2 = QFontMetrics(title_font)
            title_rect = QRectF(
                inner_rect.left(),
                inner_rect.center().y() + side * 0.12,
                inner_rect.width(),
                fm2.height() + 4,
            )
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignHCenter, self._title)

        painter.end()
