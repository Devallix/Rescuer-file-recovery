import string
from dataclasses import asdict, dataclass
from typing import Any

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Palette:
    name: str
    background: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    text: str
    text_muted: str
    text_faint: str
    accent: str
    accent_hover: str
    accent_pressed: str
    emerald: str
    success: str
    warning: str
    error: str
    focus_ring: str
    shadow: str
    scrim: str
    glass: str


DARK = Palette(
    name="dark",
    background="#0B0E14",
    surface="#12161F",
    surface_alt="#1A2030",
    surface_hover="#202839",
    border="#232B3D",
    text="#E6EAF2",
    text_muted="#8A94A8",
    text_faint="#5A6375",
    accent="#2E8CFF",
    accent_hover="#4D9FFF",
    accent_pressed="#1D6FE0",
    emerald="#2ECB85",
    success="#34E07B",
    warning="#FFB020",
    error="#FF4D5E",
    focus_ring="rgba(46, 140, 255, 0.45)",
    shadow="rgba(0, 0, 0, 0.45)",
    scrim="rgba(4, 6, 10, 0.6)",
    glass="rgba(18, 22, 31, 0.72)",
)

LIGHT = Palette(
    name="light",
    background="#F5F7FB",
    surface="#FFFFFF",
    surface_alt="#EEF1F7",
    surface_hover="#E4E9F2",
    border="#DDE3EE",
    text="#141A26",
    text_muted="#5B6472",
    text_faint="#98A1B0",
    accent="#1D7DEB",
    accent_hover="#3B90F2",
    accent_pressed="#1566C4",
    emerald="#17A864",
    success="#22B25A",
    warning="#E8930C",
    error="#E63B4E",
    focus_ring="rgba(29, 125, 235, 0.4)",
    shadow="rgba(16, 24, 40, 0.12)",
    scrim="rgba(10, 14, 22, 0.35)",
    glass="rgba(255, 255, 255, 0.78)",
)

PALETTES: dict[str, Palette] = {"dark": DARK, "light": LIGHT}

FONT_FAMILIES = ["Inter", "Segoe UI Variable", "Segoe UI", "Arial"]
MONO_FAMILIES = ["JetBrains Mono", "Cascadia Code", "Consolas", "monospace"]


def _qss(p: Palette) -> str:
    t = asdict(p)
    return string.Template(
        f"""
    QMainWindow, QWidget {{
        background: $background;
        color: $text;
    }}
    QLabel {{ color: $text; background: transparent; }}
    QLabel[muted="true"] {{ color: $text_muted; }}
    QLabel[faint="true"] {{ color: $text_faint; }}

    QFrame#Card {{
        background: $surface;
        border: 1px solid $border;
        border-radius: 14px;
    }}
    QFrame#Glass {{
        background: $glass;
        border: 1px solid $border;
        border-radius: 16px;
    }}
    QFrame#NavRail {{
        background: $surface;
        border: none;
        border-right: 1px solid $border;
    }}
    QFrame#PageHeader {{ background: transparent; border: none; }}
    QFrame#Hairline {{ background: $border; border: none; }}

    QPushButton {{
        background: $surface_alt;
        color: $text;
        border: 1px solid $border;
        border-radius: 9px;
        padding: 8px 16px;
        font-weight: 500;
        outline: none;
    }}
    QPushButton:hover {{ background: $surface_hover; }}
    QPushButton:pressed {{ background: $surface_alt; }}
    QPushButton:disabled {{ color: $text_faint; }}
    QPushButton:focus {{
        border: 2px solid $accent;
        padding: 7px 15px;
    }}
    QPushButton#Primary {{
        background: $accent;
        border: 1px solid $accent;
        color: #FFFFFF;
        font-weight: 600;
        outline: none;
    }}
    QPushButton#Primary:hover {{ background: $accent_hover; }}
    QPushButton#Primary:pressed {{ background: $accent_pressed; }}
    QPushButton#Primary:focus {{
        border: 2px solid #FFFFFF;
        padding: 7px 15px;
    }}
    QPushButton#Ghost {{ background: transparent; border: 1px solid $border; outline: none; }}
    QPushButton#Ghost:hover {{ background: $surface_alt; }}
    QPushButton#Ghost:focus {{ border: 2px solid $accent; }}
    QPushButton#Ghost:checked {{ background: rgba(46,140,255,0.14); color: $accent; border-color: $accent; }}
    QPushButton#Danger {{ color: $error; border-color: rgba(255,77,94,0.4); }}
    QPushButton#Danger:hover {{ background: rgba(255,77,94,0.12); }}
    QPushButton#Danger:focus {{ border: 2px solid $error; }}
    QPushButton#Success {{ background: $emerald; border: 1px solid $emerald; color: #FFFFFF; font-weight: 600; }}

    QToolButton {{
        background: transparent;
        border: none;
        border-radius: 8px;
        color: $text_muted;
        padding: 6px;
    }}
    QToolButton:hover {{ background: $surface_alt; color: $text; }}
    QToolButton:checked {{ background: rgba(46,140,255,0.14); color: $accent; }}

    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: $surface_alt;
        border: 1px solid $border;
        border-radius: 9px;
        padding: 8px 12px;
        color: $text;
        selection-background-color: $accent;
        selection-color: #FFFFFF;
        outline: none;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border: 2px solid $accent;
        padding: 7px 11px;
    }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: $surface;
        border: 1px solid $border;
        border-radius: 8px;
        selection-background-color: rgba(46,140,255,0.18);
        selection-color: $text;
        outline: none;
    }}

    QCheckBox, QRadioButton {{ spacing: 8px; color: $text; background: transparent; outline: none; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px; }}
    QCheckBox::indicator {{ border: 1px solid $border; border-radius: 5px; background: $surface_alt; }}
    QCheckBox::indicator:checked {{ background: $accent; border-color: $accent; }}
    QCheckBox::indicator:hover {{ border-color: $accent; }}
    QCheckBox::indicator:focus {{ border: 2px solid $accent; }}
    QRadioButton::indicator {{ border: 1px solid $border; border-radius: 9px; background: $surface_alt; }}
    QRadioButton::indicator:checked {{ background: $accent; border-color: $accent; }}
    QRadioButton::indicator:focus {{ border: 2px solid $accent; }}

    QListWidget, QTreeWidget, QTableWidget {{
        background: $surface;
        border: 1px solid $border;
        border-radius: 12px;
        outline: none;
    }}
    QListWidget::item, QTreeWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: $surface_hover; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: rgba(46,140,255,0.16);
        color: $text;
    }}
    QListWidget::item:focus, QTreeWidget::item:focus {{
        border: 2px solid $accent;
        border-radius: 8px;
        background: rgba(46,140,255,0.10);
    }}
    QHeaderView::section {{
        background: $surface_alt;
        color: $text_muted;
        border: none;
        border-bottom: 1px solid $border;
        padding: 8px 10px;
        font-weight: 600;
    }}
    QTableWidget {{ gridline-color: transparent; }}
    QTableWidget::item {{ padding: 6px 8px; border: none; }}
    QTableWidget::item:selected {{ background: rgba(46,140,255,0.16); color: $text; }}
    QTableWidget::item:focus {{
        border: 2px solid $accent;
        background: rgba(46,140,255,0.10);
    }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: $surface_hover;
        border-radius: 5px;
        min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: $text_faint; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: $surface_hover;
        border-radius: 5px;
        min-width: 32px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QProgressBar {{
        background: $surface_alt;
        border: none;
        border-radius: 6px;
        height: 12px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{ background: $accent; border-radius: 6px; }}
    QProgressBar#Success::chunk {{ background: $emerald; }}

    QMenu {{
        background: $surface;
        border: 1px solid $border;
        border-radius: 10px;
        padding: 6px;
    }}
    QMenu::item {{ padding: 7px 22px; border-radius: 7px; }}
    QMenu::item:selected {{ background: rgba(46,140,255,0.16); }}
    QMenu::separator {{ height: 1px; background: $border; margin: 5px 8px; }}

    QToolTip {{
        background: $surface;
        color: $text;
        border: 1px solid $border;
        border-radius: 6px;
        padding: 5px 8px;
    }}

    QSplitter::handle {{ background: $border; }}
    QStatusBar {{ background: $surface; color: $text_muted; border-top: 1px solid $border; }}

    QTabWidget::pane {{ border: 1px solid $border; border-radius: 10px; background: $surface; }}
    QTabBar::tab {{
        background: transparent;
        color: $text_muted;
        padding: 8px 16px;
        border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: $accent; border-bottom: 2px solid $accent; }}
    QTabBar::tab:hover {{ color: $text; }}
    """
    ).safe_substitute(**t)


def apply_theme(app: QApplication, palette: Palette) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(_qss(palette))


def get_palette(name: str) -> Palette:
    return PALETTES.get(name, DARK)


def system_font(point_size: int = 10) -> QFont:
    return QFont(FONT_FAMILIES[1] if len(FONT_FAMILIES) else "Arial", point_size)


def mono_font(point_size: int = 10) -> QFont:
    return QFont(MONO_FAMILIES[1], point_size)
