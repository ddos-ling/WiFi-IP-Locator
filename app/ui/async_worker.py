"""Reusable background worker: run a callable off the UI thread"""
from PySide6.QtCore import QThread, Signal


class AsyncWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as exc:  # surface any failure to the UI thread
            self.failed.emit(str(exc))
        else:
            self.done.emit(result)


_keepalive = []


def detach_worker(worker):
    """Keep a running worker alive after its dialog closes.

    Reparents to None so the dialog can be destroyed without killing a
    running thread; results are simply discarded.
    """
    if worker is None:
        return
    worker.setParent(None)
    _keepalive.append(worker)
    worker.finished.connect(
        lambda w=worker: _keepalive.remove(w) if w in _keepalive else None)


class AsyncDialogMixin:
    """Mixin for dialogs that own an AsyncWorker in self._worker"""

    _worker = None

    def done(self, *args, **kwargs):
        detach_worker(self._worker)
        self._worker = None
        super().done(*args, **kwargs)
