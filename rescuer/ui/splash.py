import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QProgressBar, QSplashScreen, QVBoxLayout, QWidget

from rescuer import APP_NAME, __version__
from rescuer.constants import APP_DESCRIPTION, APP_DEVELOPER, APP_TAGLINE
from rescuer.core.theme import get_palette
from rescuer.paths import Paths

MIN_DISPLAY_MS = 4000


class SplashScreen(QSplashScreen):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._shown_at: float | None = None
        self.setWindowFlags(Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(560, 380)

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

        palette = get_palette("dark")
        self._bg = palette.background
        self._accent = palette.accent
        self._text = palette.text
        self._muted = palette.text_muted

        widget = QWidget(self)
        widget.setStyleSheet(f"background: {self._bg}; border-radius: 18px;")
        widget.setGeometry(self.rect())
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(48, 40, 48, 24)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo = QLabel(widget)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_pix = QPixmap(str(Paths.img_dir / "logo.png"))
        if not logo_pix.isNull():
            logo_pix = logo_pix.scaled(
                72, 82,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(logo_pix)
        layout.addWidget(logo)

        title = QLabel(APP_NAME)
        title.setStyleSheet(f"font-size: 36px; font-weight: 700; color: {self._text};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        tagline = QLabel(APP_TAGLINE)
        tagline.setStyleSheet(f"font-size: 15px; color: {self._muted};")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)

        description = QLabel(APP_DESCRIPTION)
        description.setStyleSheet(f"font-size: 13px; color: {self._muted};")
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(description)

        self._status = QLabel("Initializing…")
        self._status.setStyleSheet(f"font-size: 12px; color: {self._muted};")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar {{ background: {palette.surface_alt}; border: none; border-radius: 2px; }} "
            f"QProgressBar::chunk {{ background: {self._accent}; border-radius: 2px; }}"
        )
        layout.addWidget(self._progress)

        version = QLabel(f"v{__version__}")
        version.setStyleSheet(f"font-size: 12px; color: {self._muted};")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        developer = QLabel(APP_DEVELOPER)
        developer.setStyleSheet(f"font-size: 11px; color: {palette.text_faint};")
        developer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(developer)

        self._fill_timer = QTimer(self)
        self._fill_timer.setInterval(40)
        self._fill_timer.timeout.connect(self._step_progress)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._shown_at is None:
            self._shown_at = time.monotonic()
            self._fill_timer.start()

    def _step_progress(self) -> None:
        value = self._progress.value() + 1
        if value >= 100:
            value = 100
            self._fill_timer.stop()
        self._progress.setValue(value)

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def finish(self, window) -> None:
        self._status.setText("Ready")
        elapsed_ms = (time.monotonic() - self._shown_at) * 1000 if self._shown_at else MIN_DISPLAY_MS
        delay = max(0, MIN_DISPLAY_MS - elapsed_ms) + 300
        QTimer.singleShot(delay, lambda: self._fade_out(window))

    def _fade_out(self, window) -> None:
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QTimer(self)
        anim.setInterval(16)
        opacity = [1.0]

        def step():
            opacity[0] -= 0.05
            if opacity[0] <= 0:
                anim.stop()
                self.close()
                if window is not None:
                    window.show()
                return
            effect.setOpacity(opacity[0])

        anim.timeout.connect(step)
        anim.start()
