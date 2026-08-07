import logging
import logging.handlers
from pathlib import Path

from rescuer.constants import LOG_DATE_FORMAT, LOG_FORMAT


class LogManager:
    def __init__(self, log_path: Path, level: int = logging.INFO) -> None:
        self.log_path = log_path
        self._logger = logging.getLogger("rescuer")
        self._logger.setLevel(level)
        self._logger.propagate = False
        self._configure(level)

    def _configure(self, level: int) -> None:
        formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
        self._logger.handlers.clear()

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        self._logger.addHandler(console)

    def set_level(self, level: int) -> None:
        self._logger.setLevel(level)

    def get_logger(self, name: str = "rescuer") -> logging.Logger:
        return logging.getLogger(name)


def setup_logging(log_path: Path, level: int = logging.INFO) -> LogManager:
    return LogManager(log_path, level)
