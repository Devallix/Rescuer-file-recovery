from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


class StarsLabel(QWidget):
    def __init__(self, stars: int = 0, score: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self._stars = max(0, min(5, stars))
        self._score = score
        self.setFixedSize(QSize(78, 16))
        self.setToolTip(self._tooltip())

    def set_value(self, stars: int, score: int | None = None) -> None:
        self._stars = max(0, min(5, stars))
        self._score = score
        self.setToolTip(self._tooltip())
        self.update()

    def _tooltip(self) -> str:
        labels = {5: "Excellent", 4: "Good", 3: "Partial", 2: "Damaged", 1: "Poor", 0: "Unknown"}
        label = labels.get(self._stars, "Unknown")
        if self._score is not None:
            return f"{label} — quality score {self._score}/100"
        return label

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#8A94A8"), 1.4)
        filled = QColor("#FFB020")
        outline = QColor("#8A94A8")
        char_width = 14
        for i in range(5):
            x = 2 + i * char_width
            if i < self._stars:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(filled)
                self._star(painter, x, 8, 6)
            else:
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                self._star(painter, x, 8, 6)
        painter.end()

    def _star(self, painter: QPainter, cx: float, cy: float, r: float) -> None:
        import math

        points = []
        for i in range(10):
            angle = math.pi / 5 * i - math.pi / 2
            radius = r if i % 2 == 0 else r * 0.5
            points.append(QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        painter.drawPolygon(QPolygonF(points))
