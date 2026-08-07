from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Bridge(QObject):
    done = Signal(object)
    error = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn, args, kwargs, bridge: _Bridge) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._bridge = bridge

    @Slot()
    def run(self) -> None:
        result = None
        exc = None
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as err:  # noqa: BLE001
            exc = err
        try:
            if exc is not None:
                self._bridge.error.emit(exc)
            else:
                self._bridge.done.emit(result)
        except RuntimeError:
            pass


class WorkerPool:
    def __init__(self) -> None:
        self._pool = QThreadPool.globalInstance()
        self._tasks: set[_Task] = set()

    def submit(self, fn, *args, on_done=None, on_error=None, **kwargs) -> None:
        bridge = _Bridge()
        task = _Task(fn, args, kwargs, bridge)
        self._tasks.add(task)

        def _finish(*_) -> None:
            self._tasks.discard(task)

        bridge.done.connect(_finish)
        bridge.error.connect(_finish)
        if on_done:
            bridge.done.connect(on_done)
        if on_error:
            bridge.error.connect(on_error)
        self._pool.start(task)
