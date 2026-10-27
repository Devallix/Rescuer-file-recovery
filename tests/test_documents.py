from PySide6.QtWidgets import QTextBrowser

from rescuer.core.theme import DARK
from rescuer.paths import Paths
from rescuer.ui.widgets.document_dialog import DocumentDialog


def test_help_documents_exist():
    assert (Paths.docs_dir / "USER_GUIDE.md").is_file()
    assert (Paths.docs_dir / "EULA.txt").is_file()


def test_user_guide_renders_markdown(qtbot):
    text = (Paths.docs_dir / "USER_GUIDE.md").read_text(encoding="utf-8")
    dialog = DocumentDialog("User Guide", text, palette=DARK, markdown=True)
    qtbot.addWidget(dialog)

    browser = dialog.findChild(QTextBrowser)
    plain = browser.toPlainText()
    assert "Getting Started" in plain
    assert "Purpose" in plain
    assert "<table" in browser.document().toHtml()


def test_eula_renders_plain_text(qtbot):
    text = (Paths.docs_dir / "EULA.txt").read_text(encoding="utf-8")
    dialog = DocumentDialog("End User License Agreement", text, palette=DARK)
    qtbot.addWidget(dialog)

    assert "END USER LICENSE AGREEMENT" in dialog.findChild(QTextBrowser).toPlainText()
