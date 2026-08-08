import logging
import sys

from PySide6.QtCore import QLockFile, QStandardPaths, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from rescuer import APP_NAME
from rescuer.constants import DEFAULT_THEME, SINGLE_INSTANCE_ID
from rescuer.core.app_context import AppContext
from rescuer.core.logging_setup import setup_logging
from rescuer.core.theme import apply_theme, get_palette
from rescuer.paths import Paths


def _acquire_single_instance() -> QLockFile | None:
    lock_path = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.TempLocation
    )
    lock = QLockFile(f"{lock_path}/{SINGLE_INSTANCE_ID}.lock")
    if not lock.tryLock(100):
        return None
    lock.setStaleLockTime(0)
    return lock


def main() -> int:
    if sys.platform == "win32":
        import ctypes

        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

    Paths.ensure_dirs()
    log_manager = setup_logging(Paths.log_path, logging.INFO)
    logger = log_manager.get_logger("rescuer.entrypoint")
    logger.info("Starting %s", APP_NAME)

    ctx = AppContext.instance()
    ctx.logger = logger

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setFont(QFont("Segoe UI Variable", 10))
    app.setWindowIcon(QIcon(str(Paths.img_dir / "logo.png")))

    lock = _acquire_single_instance()
    if lock is None:
        QMessageBox.warning(None, APP_NAME, f"{APP_NAME} is already running.")
        return 1

    theme_name = ctx.config.get("appearance.theme", DEFAULT_THEME)
    apply_theme(app, get_palette(theme_name))

    def _on_theme_changed(name: str) -> None:
        apply_theme(app, get_palette(name))

    ctx.events.theme_changed.connect(_on_theme_changed)

    from rescuer.ui.main_window import MainWindow
    from rescuer.ui.splash import SplashScreen

    splash = SplashScreen()
    splash.show()
    splash.set_status("Loading engine…")

    window = MainWindow()
    ctx.window = window
    splash.set_status("Ready")
    splash.finish(window)
    window._pages["dashboard"].refresh()

    if ctx.config.get("general.check_updates", True):
        _schedule_update_check(ctx)

    logger.info("Application window ready")
    code = app.exec()
    lock.unlock()
    logger.info("Application exited with code %s", code)
    return code


def _schedule_update_check(ctx) -> None:
    from rescuer.core.worker_pool import WorkerPool
    from rescuer.engine.updates.checker import check_for_updates, record_check
    from rescuer import __version__

    endpoint = ctx.config.get("updates.endpoint", "")
    if not endpoint:
        return

    def _done(info):
        if info is None:
            record_check(ctx.db, __version__, "up-to-date")
            return
        record_check(ctx.db, __version__, f"update-available {info.version}")
        from rescuer.engine.updates.installer import offer_update
        offer_update(ctx.window, info)

    def _error(exc):
        record_check(ctx.db, __version__, f"error: {exc}")

    pool = WorkerPool()
    pool.submit(check_for_updates, __version__, endpoint, on_done=_done, on_error=_error)


if __name__ == "__main__":
    raise SystemExit(main())
