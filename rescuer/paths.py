import os
import sys
from pathlib import Path


def _base_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base)
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base)
    return Path.home() / ".local" / "share"


def _base_cache_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base)
    return _base_data_dir()


class Paths:
    app_root = Path(__file__).resolve().parent.parent
    img_dir = app_root / "img"
    data_dir = _base_data_dir() / "Rescuer"
    cache_dir = _base_cache_dir() / "Rescuer" / "cache"
    logs_dir = data_dir / "logs"
    thumbnails_dir = cache_dir / "thumbnails"
    reports_dir = data_dir / "reports"
    sessions_dir = data_dir / "sessions"
    images_dir = data_dir / "images"
    plugins_dir = data_dir / "plugins"

    db_path = data_dir / "rescuer.db"
    log_path = logs_dir / "rescuer.log"

    @classmethod
    def ensure_dirs(cls) -> None:
        for d in (cls.data_dir, cls.cache_dir, cls.logs_dir, cls.thumbnails_dir,
                  cls.reports_dir, cls.sessions_dir, cls.images_dir):
            d.mkdir(parents=True, exist_ok=True)
