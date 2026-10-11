"""xdg-desktop-portal client: Wayland screen capture and global shortcuts.

Linux desktops with a Wayland session do not allow screen grabbing
(``QScreen.grabWindow`` returns a null pixmap) or global key grabs (the
compositor owns the keyboard).  The freedesktop portal is the supported way in:

* ``org.freedesktop.portal.Screenshot`` -- one-shot full-desktop capture.
* ``org.freedesktop.portal.GlobalShortcuts`` -- system-wide hotkeys.

Both are plain D-Bus calls, spoken through ``PySide6.QtDBus`` so no extra
dependency is needed.  Everything degrades gracefully: without a session bus
or a portal implementation the helpers simply report failure and the caller
falls back to the Windows/X11 code paths.

Two QtDBus quirks are load-bearing (see ``_RESPONSE_SLOT`` and the slot
decorators): the slot name passed to ``QDBusConnection.connect`` must be a
*str* in Qt's old-style ``"1name(Types)"`` form, and slot parameter types must
match the D-Bus wire types exactly (``uint``, not Python ``int``).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from PySide6.QtGui import QPixmap

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SESSION_INTERFACE = "org.freedesktop.portal.Session"
SCREENSHOT_INTERFACE = "org.freedesktop.portal.Screenshot"
SHORTCUTS_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"

# ``QDBusConnection.connect`` expects Qt's old-style slot signature: Qt always
# drops the first character (the SIGNAL()/SLOT() macro code digit) before
# looking the method up in the receiver's metaobject, so we prepend "1".
_RESPONSE_SLOT = "1on_response(uint,QVariantMap)"
_ACTIVATED_SLOT = "1on_activated(QDBusObjectPath,QString,qulonglong,QVariantMap)"

#: XDG application directories, most specific first.
_APP_DIRS = ("~/.local/share/applications", "/usr/local/share/applications", "/usr/share/applications")


class PortalError(RuntimeError):
    """A portal call failed (unavailable service, refusal, timeout, ...)."""


# --------------------------------------------------------------------------- #
# pure helpers (unit tested)
# --------------------------------------------------------------------------- #


def request_path(sender: str, token: str) -> str:
    """Object path the portal uses for the ``Response`` of ``token``.

    ``sender`` is the caller's unique bus name (``":1.42"``); the portal
    rewrites it the same way D-Bus does for object paths.
    """
    return f"/org/freedesktop/portal/desktop/request/{sender.lstrip(':').replace('.', '_')}/{token}"


def uri_to_path(uri: str) -> str:
    """``"file:///home/x/Screenshot.png"`` -> ``"/home/x/Screenshot.png"``."""
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return unquote(parsed.path)
    return unquote(uri)


def app_id_from_unit(unit: str) -> str | None:
    """Extract the desktop id a systemd ``app-*.scope`` unit was launched for.

    Desktops launch applications in units like
    ``app-org.opengirgit.OpenGirGit-12345.scope``; the portal turns that back
    into an app id and looks up ``<id>.desktop``.  Processes started from a
    plain shell live in a terminal unit and have no app id, which makes the
    GlobalShortcuts portal refuse them.
    """
    unit = unit.strip()
    if not unit.startswith("app-"):
        return None
    for suffix in (".scope", ".service"):
        if unit.endswith(suffix):
            unit = unit[: -len(suffix)]
            break
    unit = unit[len("app-") :]
    head, _, tail = unit.rpartition("-")
    if head and tail.isdigit():
        return head
    return unit or None


def systemd_unit() -> str | None:
    """The caller's systemd unit name, parsed from ``/proc/self/cgroup``."""
    try:
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in reversed(cgroup.splitlines()):
        _, _, rest = line.partition(":")
        _, _, path = rest.partition(":")
        name = path.rstrip("/").rpartition("/")[2]
        if name.endswith((".scope", ".service")):
            return name
    return None


def desktop_file_for(app_id: str) -> str | None:
    """Path of ``<app_id>.desktop`` in the XDG application directories."""
    for directory in _APP_DIRS:
        candidate = Path(directory).expanduser() / f"{app_id}.desktop"
        if candidate.is_file():
            return str(candidate)
    return None


def portal_hotkey_app_id() -> str | None:
    """App id the portal would attribute to *this* process, if any.

    Mirrors what xdg-desktop-portal does for host applications: the systemd
    unit must be an ``app-<desktop-id>`` unit and a matching ``.desktop`` file
    must be installed.  ``None`` means GlobalShortcuts will refuse us.
    """
    unit = systemd_unit()
    if unit is None:
        return None
    app_id = app_id_from_unit(unit)
    if not app_id:
        return None
    return app_id if desktop_file_for(app_id) else None


# --------------------------------------------------------------------------- #
# D-Bus plumbing
# --------------------------------------------------------------------------- #


def _new_token(kind: str) -> str:
    """A valid object-path element, unique enough for one request."""
    return f"opengirgit_{kind}_{os.getpid()}_{int(time.time() * 1000) % 100000}"


def _object_path(value: Any) -> str:
    """``QDBusObjectPath`` -> ``str`` (``str()`` would give the repr)."""
    path = getattr(value, "path", None)
    if callable(path):
        return str(path())
    return str(value)


class _ResponseCatcher(QObject):
    """Receives ``org.freedesktop.portal.Request.Response`` signals.

    The response code is a D-Bus ``u`` (uint32); the slot must declare
    ``uint`` -- a Python ``int`` maps to ``i`` and QtDBus drops the signal
    without a word.
    """

    def __init__(self, on_response: Callable[[int, dict], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._on_response = on_response

    @Slot("uint", "QVariantMap")
    def on_response(self, response: int, results: dict) -> None:  # noqa: N802 - D-Bus name
        self._on_response(int(response), dict(results))


class _ShortcutCatcher(QObject):
    """Receives ``GlobalShortcuts.Activated`` for the bound session."""

    def __init__(self, on_activated: Callable[[str], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._on_activated = on_activated

    @Slot("QDBusObjectPath", "QString", "qulonglong", "QVariantMap")
    def on_activated(self, session: Any, shortcut_id: str, timestamp: int, options: dict) -> None:  # noqa: N802
        self._on_activated(str(shortcut_id))


class PortalClient(QObject):
    """Thin client for the two portal interfaces OpenGirGit needs.

    All methods are safe to call when no portal is running; they return
    ``None`` or raise :class:`PortalError` with a readable message.
    """

    #: ``(ok, message)`` once ``bind_shortcuts`` has been answered.
    shortcuts_bound = Signal(bool, str)
    #: A bound shortcut was pressed; carries the action id.
    shortcut_activated = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bus = QDBusConnection.sessionBus()
        self._session: str | None = None
        self._activated_catcher: _ShortcutCatcher | None = None
        self._pending: list[_ResponseCatcher] = []

    # -- availability ------------------------------------------------------ #

    def connected(self) -> bool:
        return bool(self._bus.isConnected())

    def available(self, interface: str) -> bool:
        """Whether *interface* exists on the session bus (one round trip)."""
        if not self.connected():
            return False
        try:
            return bool(QDBusInterface(PORTAL_SERVICE, PORTAL_PATH, interface, self._bus).isValid())
        except Exception:  # noqa: BLE001 - D-Bus failures are not fatal
            return False

    # -- request plumbing -------------------------------------------------- #

    def _iface(self, interface: str, path: str = PORTAL_PATH) -> QDBusInterface:
        return QDBusInterface(PORTAL_SERVICE, path, interface, self._bus)

    def _subscribe_response(self, catcher: QObject, path: str) -> bool:
        return bool(
            self._bus.connect(PORTAL_SERVICE, path, REQUEST_INTERFACE, "Response", catcher, _RESPONSE_SLOT)
        )

    def _unsubscribe_response(self, catcher: QObject, path: str) -> None:
        self._bus.disconnect(PORTAL_SERVICE, path, REQUEST_INTERFACE, "Response", catcher, _RESPONSE_SLOT)

    def _token_args(self, interface: str, method: str, args: list, token: str) -> list:
        """Add a ``handle_token`` to the options dict (always the last arg)."""
        return [*args[:-1], {**args[-1], "handle_token": token}]

    def _call(self, interface: str, method: str, args: list) -> QDBusMessage:
        if not self.connected():
            raise PortalError("no D-Bus session bus")
        reply = self._iface(interface).call(method, *args)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            raise PortalError(reply.errorMessage() or f"{method} failed")
        return reply

    def _await_response(
        self, interface: str, method: str, args: list, timeout_ms: int
    ) -> tuple[int, dict]:
        """Call a portal method and wait for its ``Response`` signal.

        The response can be delivered while the method call is still waiting,
        hence the check before entering the loop.
        """
        token = _new_token(method.lower())
        path = request_path(self._bus.baseService(), token)
        result: dict[str, Any] = {}
        loop = QEventLoop()

        def on_response(code: int, results: dict) -> None:
            result["code"] = code
            result["results"] = results
            loop.quit()

        catcher = _ResponseCatcher(on_response, self)
        self._pending.append(catcher)
        if not self._subscribe_response(catcher, path):
            raise PortalError("could not subscribe to portal responses")
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        try:
            reply = self._call(interface, method, self._token_args(interface, method, args, token))
            handle = _object_path(reply.arguments()[0]) if reply.arguments() else path
            if handle != path:  # the portal may pick its own handle
                self._unsubscribe_response(catcher, path)
                path = handle
                if not self._subscribe_response(catcher, path):
                    raise PortalError("could not subscribe to portal responses")
            if "code" not in result:
                timer.start(timeout_ms)
                loop.exec()
                timer.stop()
        finally:
            self._unsubscribe_response(catcher, path)
            if catcher in self._pending:
                self._pending.remove(catcher)
        if "code" not in result:
            raise PortalError(f"{method} timed out")
        return int(result["code"]), dict(result.get("results") or {})

    def _request(
        self,
        interface: str,
        method: str,
        args: list,
        on_response: Callable[[int, dict], None],
        timeout_ms: int,
    ) -> str:
        """Fire-and-forget portal request; *on_response* runs later.

        Used where the answer can take as long as the user needs (a desktop
        confirmation dialog), so the caller must stay responsive.  A timed-out
        request reports ``code = -1``.
        """
        token = _new_token(method.lower())
        path = request_path(self._bus.baseService(), token)
        state = {"path": path, "done": False}
        timer = QTimer(self)
        timer.setSingleShot(True)

        def finish(code: int, results: dict) -> None:
            if state["done"]:
                return
            state["done"] = True
            timer.stop()
            self._unsubscribe_response(catcher, state["path"])
            if catcher in self._pending:
                self._pending.remove(catcher)
            on_response(code, results)

        catcher = _ResponseCatcher(finish, self)
        self._pending.append(catcher)
        timer.timeout.connect(lambda: finish(-1, {}))
        if not self._subscribe_response(catcher, path):
            raise PortalError("could not subscribe to portal responses")
        timer.start(timeout_ms)
        try:
            reply = self._call(interface, method, self._token_args(interface, method, args, token))
        except PortalError:
            timer.stop()
            self._unsubscribe_response(catcher, path)
            raise
        handle = _object_path(reply.arguments()[0]) if reply.arguments() else path
        if handle != path:
            self._unsubscribe_response(catcher, path)
            state["path"] = handle
            if not self._subscribe_response(catcher, handle):
                timer.stop()
                raise PortalError("could not subscribe to portal responses")
        return handle

    # -- screenshot -------------------------------------------------------- #

    def screenshot(self, timeout_ms: int = 15000, keep_file: bool = False) -> QPixmap | None:
        """Capture the whole desktop through the portal.

        The portal writes a PNG and returns its URI; the file is removed again
        unless *keep_file* is set, since this is a transient input for the
        vision request rather than a user-facing screenshot.
        """
        if not self.available(SCREENSHOT_INTERFACE):
            raise PortalError("the Screenshot portal is not available")
        code, results = self._await_response(
            SCREENSHOT_INTERFACE,
            "Screenshot",
            ["", {"interactive": False, "modal": False}],
            timeout_ms,
        )
        if code != 0:
            raise PortalError("screen capture was refused")
        uri = results.get("uri")
        if not uri:
            raise PortalError("the portal returned no image")
        path = uri_to_path(str(uri))
        pixmap = QPixmap(path)
        if not keep_file:
            try:
                os.unlink(path)
            except OSError:
                pass
        if pixmap.isNull():
            raise PortalError("could not read the captured image")
        return pixmap

    # -- global shortcuts -------------------------------------------------- #

    def bind_shortcuts(
        self,
        shortcuts: list[tuple[str, str, str]],
        timeout_ms: int = 120000,
    ) -> None:
        """Ask for system-wide hotkeys.  ``shortcuts`` is ``(id, label, trigger)``.

        The answer is asynchronous (desktops ask their user to confirm) and is
        reported through :attr:`shortcuts_bound`.  ``Activated`` signals are
        re-emitted as :attr:`shortcut_activated`.
        """
        if not self.available(SHORTCUTS_INTERFACE):
            raise PortalError("the GlobalShortcuts portal is not available")
        self.close()

        code, results = self._await_response(
            SHORTCUTS_INTERFACE,
            "CreateSession",
            [{"session_handle_token": _new_token("session")}],
            10000,
        )
        if code != 0:
            raise PortalError("the portal refused a shortcut session")
        session = results.get("session_handle")
        if not session:
            raise PortalError("the portal returned no session handle")
        self._session = str(session)

        self._activated_catcher = _ShortcutCatcher(
            lambda shortcut_id: self.shortcut_activated.emit(shortcut_id), self
        )
        if not self._bus.connect(
            PORTAL_SERVICE, self._session, SHORTCUTS_INTERFACE, "Activated",
            self._activated_catcher, _ACTIVATED_SLOT,
        ):
            self.close()
            raise PortalError("could not listen for shortcut activations")

        payload = [
            (shortcut_id, {"description": label, "preferred_trigger": trigger})
            for shortcut_id, label, trigger in shortcuts
            if trigger
        ]
        if not payload:
            self.close()
            self.shortcuts_bound.emit(True, "")
            return
        try:
            self._request(
                SHORTCUTS_INTERFACE,
                "BindShortcuts",
                [self._session, payload, "", {}],
                self._on_bind_response,
                timeout_ms,
            )
        except PortalError:
            self.close()
            raise

    def _on_bind_response(self, code: int, results: dict) -> None:
        if code == 0:
            self.shortcuts_bound.emit(True, "")
        elif code == -1:
            self.shortcuts_bound.emit(False, "the desktop did not answer in time")
        elif code == 1:
            self.shortcuts_bound.emit(False, "the shortcuts were cancelled")
        else:
            self.shortcuts_bound.emit(False, "the desktop refused the shortcuts")

    def close(self) -> None:
        """Close the shortcut session, if any."""
        if self._activated_catcher is not None:
            if self._session:
                try:
                    self._bus.disconnect(
                        PORTAL_SERVICE, self._session, SHORTCUTS_INTERFACE, "Activated",
                        self._activated_catcher, _ACTIVATED_SLOT,
                    )
                except Exception:  # noqa: BLE001
                    pass
                try:
                    self._iface(SESSION_INTERFACE, self._session).call("Close")
                except Exception:  # noqa: BLE001
                    pass
        self._activated_catcher = None
        self._session = None
