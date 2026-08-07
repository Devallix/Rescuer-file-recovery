import ctypes
import subprocess
from dataclasses import dataclass, field


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def require_admin() -> bool:
    if is_admin():
        return True
    try:
        return bool(
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "pythonw.exe", "", None, 1
            )
        )
    except Exception:
        return False
