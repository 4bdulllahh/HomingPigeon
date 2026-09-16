"""Background work primitives.

Nothing that can block, such as a DNS lookup, an SMTP handshake, reading a 50 MB
spreadsheet, scoring an email body, may run on the UI thread. Everything in
this package runs on a ``QThreadPool`` worker and talks back to the UI through
``pyqtSignal``, which Qt queues onto the main thread automatically. That is the
only safe way to touch a widget from another thread.

Two shapes are provided:

``Task``      one-shot: run a callable, emit ``finished`` or ``failed``.
``Worker``    long-running with progress; subclass and implement ``work()``.
"""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal


class Signals(QObject):
    """Signals live on a QObject; QRunnable is not one, so it owns an instance."""

    finished = pyqtSignal(object)        # the return value
    failed = pyqtSignal(str)             # a human-readable message
    progress = pyqtSignal(int, int, str)  # done, total, detail
    message = pyqtSignal(str, str)       # text, level
    done = pyqtSignal()                  # always, success or not


class Task(QRunnable):
    """Run one callable off the UI thread and deliver the result by signal.

    ``Task(work).start(on_result=..., on_error=...)`` is the whole API. Results
    arrive on the UI thread, so the callbacks may touch widgets freely.
    """

    def __init__(self, function: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = Signals()
        self._cancelled = False
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:  # executed on a pool thread
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as error:  # noqa: BLE001 - a worker must never kill the app
            traceback.print_exc()
            if not self._cancelled:
                self.signals.failed.emit(_friendly(error))
        else:
            if not self._cancelled:
                self.signals.finished.emit(result)
        finally:
            if not self._cancelled:
                self.signals.done.emit()

    def start(self, on_result=None, on_error=None, on_done=None) -> "Task":
        if on_result:
            self.signals.finished.connect(on_result)
        if on_error:
            self.signals.failed.connect(on_error)
        if on_done:
            self.signals.done.connect(on_done)
        pool().start(self)
        return self


class Worker(QRunnable):
    """Long-running job with progress reporting and cooperative cancellation."""

    def __init__(self):
        super().__init__()
        self.signals = Signals()
        self._cancelled = False
        self.setAutoDelete(True)

    # -- from the UI thread --------------------------------------------------
    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    # -- from the worker thread ----------------------------------------------
    def report(self, done: int, total: int, detail: str = "") -> None:
        if not self._cancelled:
            self.signals.progress.emit(done, total, detail)

    def log(self, text: str, level: str = "info") -> None:
        if not self._cancelled:
            self.signals.message.emit(text, level)

    def work(self) -> Any:
        raise NotImplementedError

    def run(self) -> None:
        try:
            result = self.work()
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            if not self._cancelled:
                self.signals.failed.emit(_friendly(error))
        else:
            if not self._cancelled:
                self.signals.finished.emit(result)
        finally:
            if not self._cancelled:
                self.signals.done.emit()

    def start(self) -> "Worker":
        pool().start(self)
        return self


_pool: QThreadPool | None = None


def pool() -> QThreadPool:
    """The shared pool. Sized for I/O-bound work, not for CPU count.

    Most jobs here sit waiting on a socket, so a low-spec machine still wants
    several threads; it just must not want hundreds.
    """
    global _pool
    if _pool is None:
        _pool = QThreadPool()
        _pool.setMaxThreadCount(max(4, min(8, (_pool.maxThreadCount() or 4) * 2)))
    return _pool


def shutdown(timeout_ms: int = 3000) -> None:
    """Let running jobs finish before the process exits."""
    if _pool is not None:
        _pool.waitForDone(timeout_ms)


def _friendly(error: Exception) -> str:
    text = str(error).strip()
    return text or error.__class__.__name__
