from rescuer.core.theme import LIGHT, DARK, _qss, apply_theme, get_palette
from PySide6.QtWidgets import QApplication


def test_palettes_have_tokens():
    for p in (DARK, LIGHT):
        qss = _qss(p)
        for token in ("background", "surface", "accent", "text", "border"):
            assert f"${token}" not in qss, f"unsubstituted token {token}"


def test_qss_contains_key_rules():
    qss = _qss(DARK)
    for rule in ("QPushButton", "QFrame#Card", "QTableWidget", "QScrollBar"):
        assert rule in qss


def test_get_palette_fallback():
    assert get_palette("nope") is DARK


def test_apply_theme_sets_stylesheet(qtbot):
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    apply_theme(app, DARK)
    assert app.styleSheet()
