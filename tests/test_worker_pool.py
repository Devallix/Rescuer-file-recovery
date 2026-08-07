from PySide6.QtCore import QThread
from PySide6.QtTest import QSignalSpy

from rescuer.core.worker_pool import WorkerPool


def test_callback_runs_on_main_thread(qtbot):
    pool = WorkerPool()
    results = {}

    def work():
        return "payload"

    def on_done(value):
        results["value"] = value
        results["thread"] = QThread.currentThread()

    pool.submit(work, on_done=on_done)
    qtbot.waitUntil(lambda: "value" in results, timeout=5000)

    assert results["value"] == "payload"
    assert results["thread"] is QThread.currentThread()


def test_error_callback(qtbot):
    pool = WorkerPool()
    results = {}

    def work():
        raise ValueError("boom")

    def on_error(exc):
        results["error"] = exc

    pool.submit(work, on_error=on_error)
    qtbot.waitUntil(lambda: "error" in results, timeout=5000)
    assert isinstance(results["error"], ValueError)
