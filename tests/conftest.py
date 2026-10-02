"""Make the two component packages importable in tests without installation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for folder in ("server", "client"):
    path = str(ROOT / folder)
    if path not in sys.path:
        sys.path.insert(0, path)

# Qt UI tests run without a display. The embedded QtWebEngine used for math and
# mermaid answers additionally needs the Chromium sandbox off in CI, and the
# shared-OpenGL attribute must be set before the QApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage"
)
try:  # pragma: no cover - PySide6 missing: the Qt tests skip themselves
    from PySide6.QtCore import QCoreApplication, Qt

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
except Exception:  # noqa: BLE001
    pass


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _flush_deferred_deletes():
    """Deliver ``deleteLater()`` deletions after every test.

    Tests run outside a Qt event loop, so deferred deletes would otherwise
    never be processed; a surviving ``QWebEnginePage`` crashes the interpreter
    when the default profile is released at exit.
    """
    yield
    try:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
    except Exception:  # noqa: BLE001
        return
    app = QApplication.instance()
    if app is None:
        return
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
