import datetime

from rescuer.ui.pages.wizard_page import _fmt_elapsed


def _page(allowed: int):
    from rescuer.ui.pages.wizard_page import WizardPage

    page = WizardPage.__new__(WizardPage)
    page._allowed = allowed
    return page


def test_fmt_elapsed_under_minute():
    assert _fmt_elapsed(datetime.timedelta(seconds=7)) == "00:07"


def test_fmt_elapsed_minutes():
    assert _fmt_elapsed(datetime.timedelta(seconds=65)) == "01:05"


def test_fmt_elapsed_hours():
    assert _fmt_elapsed(datetime.timedelta(seconds=3723)) == "1:02:03"


def test_step_reachable_while_scanning():
    page = _page(2)
    assert page._step_reachable(0)
    assert page._step_reachable(2)
    assert not page._step_reachable(3)
    assert not page._step_reachable(4)


def test_step_reachable_after_scan_ends():
    page = _page(3)
    assert page._step_reachable(3)
    assert page._step_reachable(4) is True


def test_step_reachable_after_recovery():
    page = _page(4)
    assert page._step_reachable(4) is True
