import logging

from PySide6.QtCore import QObject, QThread, Signal

from rescuer.engine.imaging.dumper import create_image
from rescuer.exceptions import ImagingError

log = logging.getLogger("rescuer.engine.imaging")


class ImagingSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)


class ImagingWorker(QThread):
    def __init__(
        self,
        source_path: str,
        dest_path: str,
        signals: ImagingSignals,
        cancel_flag: list[bool],
    ) -> None:
        super().__init__()
        self._source = source_path
        self._dest = dest_path
        self._signals = signals
        self._cancel = cancel_flag

    def run(self) -> None:
        try:
            result = create_image(
                self._source,
                self._dest,
                progress=self._progress,
                cancel_flag=self._cancel,
            )
            if self._cancel and self._cancel[0]:
                self._signals.failed.emit("Imaging cancelled by user")
            else:
                self._signals.finished.emit(result)
        except Exception as exc:
            log.exception("imaging failed for %s -> %s", self._source, self._dest)
            self._signals.failed.emit(str(exc))

    def _progress(self, done: int, total: int) -> None:
        self._signals.progress.emit(done, total)


class ImagingController(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._signals = ImagingSignals()
        self._cancel: list[bool] = [False]
        self._worker: ImagingWorker | None = None
        self._signals.progress.connect(self.progress)
        self._signals.finished.connect(self.finished)
        self._signals.failed.connect(self.failed)

    @property
    def running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def start(self, source_path: str, dest_path: str) -> None:
        if self.running:
            raise ImagingError("An imaging job is already in progress")
        self._cancel = [False]
        self._worker = ImagingWorker(source_path, dest_path, self._signals, self._cancel)
        self._worker.start()

    def cancel(self) -> None:
        self._cancel[0] = True
