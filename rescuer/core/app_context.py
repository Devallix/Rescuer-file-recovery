import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from rescuer.core.database import Config, Database
from rescuer.paths import Paths


class EventBus(QObject):
    drives_changed = Signal()
    scan_started = Signal(int)
    scan_progress = Signal(int, float)
    scan_finished = Signal(int)
    scan_error = Signal(int, str)
    scan_blocked = Signal(str, str)
    files_recovered = Signal(list)
    theme_changed = Signal(str)
    settings_changed = Signal(str, object)
    open_device_requested = Signal(object)
    quick_action_requested = Signal(str)


class AppContext:
    _instance: "AppContext | None" = None

    def __init__(self) -> None:
        Paths.ensure_dirs()
        self.paths = Paths
        self.db = Database(Paths.db_path, self._migrations_dir())
        self.config = Config(self.db)
        self.events = EventBus()
        self.logger = logging.getLogger("rescuer")
        self.app = None
        self.window = None

    @staticmethod
    def _migrations_dir() -> Path:
        return Path(__file__).resolve().parent.parent / "data" / "migrations"

    @classmethod
    def instance(cls) -> "AppContext":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
