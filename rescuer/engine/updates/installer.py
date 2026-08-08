import datetime
import logging
import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from rescuer import APP_NAME
from rescuer.engine.updates.checker import UpdateInfo, UpdateError, download_update, verify_sha256
from rescuer.paths import Paths

log = logging.getLogger("rescuer.engine.updates.installer")


def _download_with_progress(parent, info: UpdateInfo) -> str:
    dest = str(Paths.cache_dir / f"Rescuer_{info.version}.zip")
    dialog = QProgressDialog("Downloading update…", "Cancel", 0, 100, parent)
    dialog.setWindowTitle(f"Updating {APP_NAME}")
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    state = {"cancelled": False}

    def _cancel() -> None:
        state["cancelled"] = True

    dialog.canceled.connect(_cancel)

    def _progress(done: int, total: int) -> None:
        if state["cancelled"]:
            return
        percent = int(done / total * 100) if total else 0
        dialog.setValue(percent)
        dialog.setLabelText(
            f"Downloading update… {done / (1 << 20):.1f} MB / "
            f"{total / (1 << 20):.1f} MB"
        )

    try:
        path = download_update(info.url, dest=dest, progress=_progress)
    except UpdateError as exc:
        dialog.close()
        raise exc

    if state["cancelled"]:
        dialog.close()
        try:
            os.remove(dest)
        except OSError:
            pass
        raise UpdateError("Download cancelled.")

    if info.sha256 and not verify_sha256(path, info.sha256):
        dialog.close()
        try:
            os.remove(path)
        except OSError:
            pass
        raise UpdateError("Downloaded update failed checksum verification.")

    dialog.setValue(100)
    dialog.close()
    return path


def _build_swap_bat(install_dir: str, zip_path: str, new_exe: str) -> str:
    """Write a detached batch script that swaps the whole install folder.

    The batch lives in the parent of ``install_dir`` so it survives the rename
    of the install folder itself. It renames the old folder aside (rollback
    target), extracts the update zip into the original path, cleans up, and
    relaunches.

    ``ping`` is used for sleeping instead of ``timeout`` because ``timeout``
    refuses to run when there is no console attached (the updater is launched
    with CREATE_NO_WINDOW), which would let the old instance still be holding
    the single-instance lock when the new one starts.
    """
    parent = os.path.dirname(install_dir)
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    old_name = os.path.basename(install_dir) + f".old_{stamp}"
    old_dir = os.path.join(parent, old_name)
    base_name = os.path.basename(install_dir)
    bat_path = os.path.join(parent, f"rescuer_updater_{stamp}.bat")
    with open(bat_path, "w", encoding="ascii") as fh:
        fh.write(
            "@echo off\r\n"
            "setlocal\r\n"
            f'set "OLD={old_dir}"\r\n'
            f'set "INSTALL={install_dir}"\r\n'
            f'set "ZIP={zip_path}"\r\n'
            f'set "NEWEXE={new_exe}"\r\n'
            "set ATTEMPTS=0\r\n"
            "set EXITCODE=0\r\n"
            "ping -n 4 127.0.0.1 >nul\r\n"
            'rmdir /s /q "%OLD%" >nul 2>&1\r\n'
            ":retry_rename\r\n"
            f'ren "%INSTALL%" "{old_name}" >nul 2>&1\r\n'
            "if not errorlevel 1 goto swapped\r\n"
            "set /a ATTEMPTS+=1\r\n"
            'if %ATTEMPTS% GEQ 30 goto fail\r\n'
            "ping -n 2 127.0.0.1 >nul\r\n"
            "goto retry_rename\r\n"
            ":swapped\r\n"
            f'powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath \'%ZIP%\' -DestinationPath \'%INSTALL%\' -Force"\r\n'
            "if errorlevel 1 goto rollback\r\n"
            'if not exist "%NEWEXE%" goto rollback\r\n'
            'rmdir /s /q "%OLD%" >nul 2>&1\r\n'
            'del /q "%ZIP%" >nul 2>&1\r\n'
            'start "" "%NEWEXE%"\r\n'
            "goto done\r\n"
            ":rollback\r\n"
            'rmdir /s /q "%INSTALL%" >nul 2>&1\r\n'
            f'ren "%OLD%" "{base_name}" >nul 2>&1\r\n'
            "set EXITCODE=1\r\n"
            "goto done\r\n"
            ":fail\r\n"
            "set EXITCODE=1\r\n"
            ":done\r\n"
            '(goto) 2>nul & del "%~f0" & exit /b %EXITCODE%\r\n'
        )
    return bat_path


def apply_update(parent, info: UpdateInfo) -> bool:
    """Download and install ``info``, relaunching the app after the swap."""
    try:
        new_zip = _download_with_progress(parent, info)
    except UpdateError as exc:
        QMessageBox.warning(parent, "Update failed", str(exc))
        return False

    if not getattr(sys, "frozen", False):
        QMessageBox.information(
            parent,
            "Update downloaded",
            f"Rescuer {info.version} was downloaded to:\n{new_zip}\n\n"
            "(Running from source — replace the distribution folder manually.)",
        )
        return True

    current = sys.executable
    install_dir = os.path.dirname(current)
    updater = _build_swap_bat(install_dir, new_zip, current)

    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    try:
        subprocess.Popen(
            ["cmd", "/c", updater],
            cwd=os.path.dirname(install_dir),
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
        )
    except OSError as exc:
        QMessageBox.warning(
            parent, "Update failed", f"Could not start the updater: {exc}"
        )
        return False

    from PySide6.QtWidgets import QApplication

    window = parent.window() if parent is not None else None
    if hasattr(window, "set_quitting"):
        window.set_quitting(True)
    QApplication.quit()
    return True


def offer_update(parent, info: UpdateInfo) -> bool:
    """Present an update prompt and, if accepted, download and install it."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Update available")
    box.setText(f"Rescuer {info.version} is available.")
    notes = (info.notes or "").strip()
    if notes:
        box.setInformativeText(notes)
    update_btn = box.addButton("Download & install", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(update_btn)
    box.exec()
    if box.clickedButton() is not update_btn:
        return False
    return apply_update(parent, info)
