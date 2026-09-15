"""QThread helpers for off-UI-thread work."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

from .api import Cancelled


class FunctionWorker(QThread):
    """Run ``fn()`` in a thread; emit its result or the error message."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], parent: Any = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D102
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class StreamWorker(QThread):
    """Consume an SSE stream in a thread.

    ``fn(cancel, on_chunk) -> str`` should call ``on_chunk`` for every delta and
    return the assembled answer; it must honour ``cancel()`` (the api client
    passes it through to the HTTP stream).
    """

    chunk = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        fn: Callable[[Callable[[], bool], Callable[[str], None]], str],
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._fn = fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:  # noqa: D102
        try:
            answer = self._fn(self.is_cancelled, self.chunk.emit)
        except Cancelled:
            self.cancelled.emit()
            return
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        if self._cancelled:
            self.cancelled.emit()
            return
        self.succeeded.emit(answer)
