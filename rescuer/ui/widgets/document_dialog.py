from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
)

from rescuer.core.theme import Palette, mono_font


class DocumentDialog(QDialog):
    """Read-only popup viewer for the bundled help documents."""

    def __init__(
        self,
        title: str,
        text: str,
        *,
        palette: Palette,
        markdown: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(880, 700)
        self.setMinimumSize(620, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(heading)

        browser = QTextBrowser(self)
        browser.setObjectName("DocumentViewer")
        browser.setReadOnly(True)
        browser.setOpenExternalLinks(True)
        browser.setFrameShape(QFrame.Shape.NoFrame)
        browser.setStyleSheet(
            f"QTextBrowser#DocumentViewer {{"
            f" background: {palette.surface};"
            f" border: 1px solid {palette.border};"
            f" border-radius: 10px;"
            f" color: {palette.text};"
            " padding: 10px 16px;"
            "}"
        )

        if markdown:
            browser.document().setDefaultStyleSheet(self._markdown_css(palette))
            browser.setMarkdown(text)
        else:
            browser.setFont(mono_font(9))
            browser.setPlainText(text)
        layout.addWidget(browser, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _markdown_css(palette: Palette) -> str:
        return f"""
            h1, h2, h3, h4, h5 {{ color: {palette.text}; }}
            a {{ color: {palette.accent}; }}
            code {{ font-family: Consolas, monospace; color: {palette.emerald}; }}
            pre {{ background: {palette.surface_alt}; color: {palette.text}; }}
            blockquote {{ color: {palette.text_muted}; }}
            th {{ background: {palette.surface_alt}; }}
            td, th {{ border: 1px solid {palette.border}; padding: 4px; }}
        """
