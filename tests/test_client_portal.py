"""Pure helpers of the xdg-desktop-portal client (skipped without PySide6)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opengirgit import portal  # noqa: E402
from PySide6.QtDBus import QDBusMessage, QDBusObjectPath  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


# -- paths / URIs ----------------------------------------------------------- #


def test_request_path_rewrites_the_sender_name():
    path = portal.request_path(":1.42", "token1")
    assert path == "/org/freedesktop/portal/desktop/request/1_42/token1"


def test_uri_to_path():
    assert portal.uri_to_path("file:///home/x/Pictures/Screenshot.png") == "/home/x/Pictures/Screenshot.png"
    assert portal.uri_to_path("file:///home/a%20b/x.png") == "/home/a b/x.png"
    assert portal.uri_to_path("/already/a/path") == "/already/a/path"


def test_object_path_unwraps_qdbus_object_path():
    assert portal._object_path(QDBusObjectPath("/a/b")) == "/a/b"  # noqa: SLF001
    assert portal._object_path("/plain") == "/plain"


# -- app id resolution (mirrors xdg-desktop-portal) ------------------------- #


def test_app_id_from_unit():
    assert portal.app_id_from_unit("app-org.opengirgit.OpenGirGit-12345.scope") == "org.opengirgit.OpenGirGit"
    assert portal.app_id_from_unit("app-org.gnome.Nautilus-9.service") == "org.gnome.Nautilus"
    assert portal.app_id_from_unit("app-foo.scope") == "foo"
    assert portal.app_id_from_unit("ptyxis-spawn-6cdb.scope") is None
    assert portal.app_id_from_unit("gnome-terminal-server.service") is None
    assert portal.app_id_from_unit("") is None


def test_desktop_file_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(portal, "_APP_DIRS", (str(tmp_path),))
    desktop = tmp_path / "org.example.App.desktop"
    desktop.write_text("[Desktop Entry]\nType=Application\n", encoding="utf-8")
    assert portal.desktop_file_for("org.example.App") == str(desktop)
    assert portal.desktop_file_for("org.example.Other") is None


def test_portal_hotkey_app_id_requires_unit_and_desktop_file(tmp_path, monkeypatch):
    monkeypatch.setattr(portal, "_APP_DIRS", (str(tmp_path),))
    monkeypatch.setattr(
        portal, "systemd_unit", lambda: "app-org.example.App-77.scope"
    )
    assert portal.portal_hotkey_app_id() is None  # no .desktop file yet
    (tmp_path / "org.example.App.desktop").write_text("[Desktop Entry]\n", encoding="utf-8")
    assert portal.portal_hotkey_app_id() == "org.example.App"
    monkeypatch.setattr(portal, "systemd_unit", lambda: "ptyxis-spawn-x.scope")
    assert portal.portal_hotkey_app_id() is None


# -- signal plumbing -------------------------------------------------------- #


def test_response_catcher_registers_the_wire_type_slot(qt_app):
    """``uint`` (not Python ``int``) matters: QtDBus drops mismatched signals."""
    catcher = portal._ResponseCatcher(lambda code, results: None)  # noqa: SLF001
    meta = catcher.metaObject()
    signatures = {
        bytes(meta.method(i).methodSignature()).decode() for i in range(meta.methodCount())
    }
    assert "on_response(uint,QVariantMap)" in signatures
    assert portal._RESPONSE_SLOT == "1on_response(uint,QVariantMap)"  # noqa: SLF001


def test_shortcut_catcher_registers_the_activated_slot(qt_app):
    catcher = portal._ShortcutCatcher(lambda shortcut_id: None)  # noqa: SLF001
    meta = catcher.metaObject()
    signatures = {
        bytes(meta.method(i).methodSignature()).decode() for i in range(meta.methodCount())
    }
    assert "on_activated(QDBusObjectPath,QString,qulonglong,QVariantMap)" in signatures


# -- request flow ----------------------------------------------------------- #


def _reply_message() -> QDBusMessage:
    return QDBusMessage.createMethodCall(
        portal.PORTAL_SERVICE, portal.PORTAL_PATH, portal.SCREENSHOT_INTERFACE, "Screenshot"
    )


def test_await_response_accepts_a_response_delivered_during_the_call(qt_app, monkeypatch):
    """The portal may answer while the method call is still blocking."""
    client = portal.PortalClient()
    seen: list[str] = []

    def fake_subscribe(catcher, path):
        seen.append(path)
        catcher.on_response(0, {"uri": "file:///tmp/x.png"})
        return True

    monkeypatch.setattr(client, "_subscribe_response", fake_subscribe)
    monkeypatch.setattr(client, "_unsubscribe_response", lambda catcher, path: None)
    monkeypatch.setattr(client, "_call", lambda *args, **kwargs: _reply_message())
    code, results = client._await_response(  # noqa: SLF001
        portal.SCREENSHOT_INTERFACE, "Screenshot", ["", {}], timeout_ms=100
    )
    assert code == 0
    assert results["uri"] == "file:///tmp/x.png"
    assert seen and seen[0].startswith("/org/freedesktop/portal/desktop/request/")


def test_await_response_times_out(qt_app, monkeypatch):
    client = portal.PortalClient()
    monkeypatch.setattr(client, "_subscribe_response", lambda catcher, path: True)
    monkeypatch.setattr(client, "_unsubscribe_response", lambda catcher, path: None)
    monkeypatch.setattr(client, "_call", lambda *args, **kwargs: _reply_message())
    with pytest.raises(portal.PortalError, match="timed out"):
        client._await_response(  # noqa: SLF001
            portal.SCREENSHOT_INTERFACE, "Screenshot", ["", {}], timeout_ms=10
        )


def test_call_surfaces_dbus_errors(qt_app, monkeypatch):
    client = portal.PortalClient()
    monkeypatch.setattr(
        client, "_iface", lambda interface, path=portal.PORTAL_PATH: _StubInterface()
    )
    monkeypatch.setattr(client, "connected", lambda: True)
    with pytest.raises(portal.PortalError, match="An app id is required"):
        client._call(portal.SHORTCUTS_INTERFACE, "CreateSession", [{}])  # noqa: SLF001


class _StubInterface:
    def call(self, method, *args):
        request = QDBusMessage.createMethodCall(
            portal.PORTAL_SERVICE, portal.PORTAL_PATH, portal.SHORTCUTS_INTERFACE, method
        )
        return request.createErrorReply(
            "org.freedesktop.portal.Error.NotAllowed", "An app id is required"
        )


def test_unavailable_portal_reports_cleanly(qt_app, monkeypatch):
    client = portal.PortalClient()
    monkeypatch.setattr(client, "available", lambda interface: False)
    with pytest.raises(portal.PortalError, match="not available"):
        client.screenshot()
    with pytest.raises(portal.PortalError, match="not available"):
        client.bind_shortcuts([("ask", "ask", "ALT+SHIFT+a")])


def test_bind_response_maps_codes(qt_app, monkeypatch):
    client = portal.PortalClient()
    events: list[tuple[bool, str]] = []
    client.shortcuts_bound.connect(lambda ok, message: events.append((ok, message)))
    client._on_bind_response(0, {})  # noqa: SLF001
    client._on_bind_response(1, {})  # noqa: SLF001
    client._on_bind_response(-1, {})  # noqa: SLF001
    client._on_bind_response(2, {})  # noqa: SLF001
    assert [ok for ok, _ in events] == [True, False, False, False]
    assert "cancelled" in events[1][1]
    assert "in time" in events[2][1]
    assert "refused" in events[3][1]


def test_close_without_session_is_safe(qt_app):
    portal.PortalClient().close()
