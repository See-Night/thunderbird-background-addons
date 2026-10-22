#!/usr/bin/python3
"""Linux StatusNotifierItem + DBusMenu bridge for one Thunderbird process.

Native messaging stdout is reserved for length-prefixed JSON. No mail is read.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import threading

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

SNI_XML = """<node><interface name="org.kde.StatusNotifierItem">
 <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
 <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
 <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
 <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
 <property name="Category" type="s" access="read"/>
 <property name="Id" type="s" access="read"/>
 <property name="Title" type="s" access="read"/>
 <property name="Status" type="s" access="read"/>
 <property name="WindowId" type="u" access="read"/>
 <property name="IconName" type="s" access="read"/>
 <property name="IconPixmap" type="a(iiay)" access="read"/>
 <property name="IconThemePath" type="s" access="read"/>
 <property name="AttentionIconName" type="s" access="read"/>
 <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
 <property name="OverlayIconName" type="s" access="read"/>
 <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
 <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
 <property name="ItemIsMenu" type="b" access="read"/>
 <property name="Menu" type="o" access="read"/>
 <signal name="NewIcon"/><signal name="NewStatus"><arg type="s"/></signal>
</interface></node>"""

MENU_XML = """<node><interface name="com.canonical.dbusmenu">
 <property name="Version" type="u" access="read"/>
 <property name="TextDirection" type="s" access="read"/>
 <property name="Status" type="s" access="read"/>
 <property name="IconThemePath" type="as" access="read"/>
 <method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/>
  <arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
 <method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/>
  <arg type="a(ia{sv})" direction="out"/></method>
 <method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/>
  <arg type="v" direction="out"/></method>
 <method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/>
  <arg type="v" direction="in"/><arg type="u" direction="in"/></method>
 <method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
 <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
 <method name="AboutToShowGroup"><arg type="ai" direction="in"/>
  <arg type="ai" direction="out"/><arg type="ai" direction="out"/></method>
 <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
 <signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})"/><arg type="a(ias)"/></signal>
</interface></node>"""


def send_message(message, stream=None):
    payload = json.dumps(message, separators=(",", ":")).encode()
    stream = stream or sys.stdout.buffer
    stream.write(struct.pack("=I", len(payload)) + payload)
    stream.flush()


def read_exact(stream, length):
    data = bytearray()
    while len(data) < length:
        chunk = stream.read(length - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


def read_message(stream):
    size, = struct.unpack("=I", read_exact(stream, 4))
    if size > 64 * 1024:
        raise ValueError("native message exceeds command size limit")
    return json.loads(read_exact(stream, size))


def socket_dir():
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "thunderbird-background"


class Host:
    ITEMS = {1: ("显示 Thunderbird", "show"),
             2: ("隐藏到后台", "hide"), 3: ("退出 Thunderbird", "quit")}

    def __init__(self):
        self.loop = GLib.MainLoop()
        self.connection = None
        self.registrations = []
        self.watcher = None
        self.listener = None
        self.socket_path = None
        self.generation = 0
        self.watcher_owner = None

    def send(self, action, **extra):
        try:
            send_message({"action": action, **extra})
        except (BrokenPipeError, OSError):
            self.loop.quit()

    def properties(self, item):
        if item == 0:
            return {"children-display": GLib.Variant("s", "submenu")}
        if item not in self.ITEMS:
            raise ValueError("unknown menu item")
        return {"label": GLib.Variant("s", self.ITEMS[item][0]),
                "enabled": GLib.Variant("b", True), "visible": GLib.Variant("b", True)}

    def layout(self, parent, depth, names):
        properties = self.properties(parent)
        if names:
            properties = {k: v for k, v in properties.items() if k in names}
        children = []
        if parent == 0 and depth != 0:
            children = [GLib.Variant("(ia{sv}av)", self.layout(i, 0, names)) for i in self.ITEMS]
        return parent, properties, children

    def event(self, item, name):
        if item not in self.ITEMS:
            return False
        if name == "clicked":
            self.send(self.ITEMS[item][1])
        return True

    def method(self, connection, sender, path, interface, method, parameters, invocation):
        args = parameters.unpack()
        try:
            result = None
            if interface == "org.kde.StatusNotifierItem":
                if method in ("Activate", "SecondaryActivate", "ContextMenu"):
                    self.send("show")
            elif method == "GetLayout":
                result = GLib.Variant("(u(ia{sv}av))", (1, self.layout(*args)))
            elif method == "GetGroupProperties":
                ids, names = args
                ids = ids or [0, *self.ITEMS]
                result = GLib.Variant("(a(ia{sv}))", ([(i, self.layout(i, 0, names)[1]) for i in ids],))
            elif method == "GetProperty":
                result = GLib.Variant("(v)", (self.properties(args[0])[args[1]],))
            elif method == "Event":
                self.event(args[0], args[1])
            elif method == "EventGroup":
                result = GLib.Variant("(ai)", ([i for i, name, _, _ in args[0] if not self.event(i, name)],))
            elif method == "AboutToShow":
                result = GLib.Variant("(b)", (False,))
            elif method == "AboutToShowGroup":
                result = GLib.Variant("(aiai)", ([], [i for i in args[0] if i not in (0, *self.ITEMS)]))
            invocation.return_value(result)
        except (ValueError, KeyError, TypeError) as error:
            invocation.return_dbus_error("com.canonical.dbusmenu.Error", str(error))

    def get_property(self, connection, sender, path, interface, name):
        if interface == "com.canonical.dbusmenu":
            return {"Version": GLib.Variant("u", 3), "TextDirection": GLib.Variant("s", "ltr"),
                    "Status": GLib.Variant("s", "normal"), "IconThemePath": GLib.Variant("as", [])}[name]
        props = {
            "Category": ("s", "Communications"), "Id": ("s", "thunderbird-background"),
            "Title": ("s", "Thunderbird 后台运行"), "Status": ("s", "Active"),
            "WindowId": ("u", 0), "IconName": ("s", "org.mozilla.Thunderbird"), "IconThemePath": ("s", ""),
            "IconPixmap": ("a(iiay)", []), "AttentionIconName": ("s", ""),
            "AttentionIconPixmap": ("a(iiay)", []), "OverlayIconName": ("s", ""),
            "OverlayIconPixmap": ("a(iiay)", []), "ItemIsMenu": ("b", False),
            "Menu": ("o", "/MenuBar"),
            "ToolTip": ("(sa(iiay)ss)", ("org.mozilla.Thunderbird", [], "Thunderbird", "后台收信 · 点击显示 · 右键菜单退出")),
        }
        return GLib.Variant(*props[name])

    def appeared(self, connection, name, owner):
        self.generation += 1
        generation = self.generation
        self.watcher_owner = owner
        self.register_watcher(generation)

    def register_watcher(self, generation):
        if generation != self.generation or not self.watcher_owner:
            return GLib.SOURCE_REMOVE

        def registered(connection, result):
            try:
                connection.call_finish(result)
                if generation == self.generation:
                    self.send("tray", available=True)
            except GLib.Error as error:
                print(f"Tray registration failed: {error}", file=sys.stderr)
                if generation == self.generation:
                    self.send("tray", available=False)
                    GLib.timeout_add_seconds(5, self.register_watcher, generation)

        # Use the unique owner: a restarted watcher cannot confirm an old request.
        self.connection.call(self.watcher_owner, "/StatusNotifierWatcher",
                             "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem",
                             GLib.Variant("(s)", ("/StatusNotifierItem",)), None,
                             Gio.DBusCallFlags.NONE, 3000, None, registered)
        return GLib.SOURCE_REMOVE

    def vanished(self, connection, name):
        self.generation += 1
        self.watcher_owner = None
        self.send("tray", available=False)

    def stdin_reader(self):
        try:
            while True:
                read_message(sys.stdin.buffer)
        except (EOFError, ValueError, OSError):
            GLib.idle_add(self.loop.quit)

    def socket_reader(self):
        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            with client:
                try:
                    client.settimeout(1)
                    # Linux peer credentials prevent other users sending commands.
                    _, uid, _ = struct.unpack("3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if uid != os.getuid():
                        continue
                    command = client.recv(32).decode("ascii").strip()
                    if command in ("show", "hide", "quit"):
                        GLib.idle_add(self.send, command)
                        client.sendall(b"OK\n")
                except (OSError, UnicodeError):
                    pass

    def start_socket(self):
        directory = socket_dir()
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("unsafe background socket directory")
        directory.chmod(0o700)
        self.socket_path = directory / f"host-{os.getpid()}.sock"
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.socket_path))
        self.socket_path.chmod(0o600)
        self.listener.listen(4)
        threading.Thread(target=self.socket_reader, daemon=True).start()

    def run(self):
        self.send("tray", available=False)
        try:
            self.start_socket()
        except OSError as error:
            # Tray commands remain usable if the optional recovery socket fails.
            print(f"Recovery socket unavailable: {error}", file=sys.stderr)
        threading.Thread(target=self.stdin_reader, daemon=True).start()
        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            for path, xml in (("/StatusNotifierItem", SNI_XML), ("/MenuBar", MENU_XML)):
                info = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
                self.registrations.append(self.connection.register_object(path, info, self.method, self.get_property, None))
            self.connection.connect("closed", lambda *_: (self.send("tray", available=False), self.loop.quit()))
            self.watcher = Gio.bus_watch_name_on_connection(self.connection,
                "org.kde.StatusNotifierWatcher", Gio.BusNameWatcherFlags.NONE, self.appeared, self.vanished)
            self.loop.run()
        except GLib.Error as error:
            print(f"Session tray unavailable: {error}", file=sys.stderr)
        finally:
            if self.watcher:
                Gio.bus_unwatch_name(self.watcher)
            for registration in self.registrations:
                self.connection.unregister_object(registration)
            if self.listener:
                self.listener.close()
            if self.socket_path:
                self.socket_path.unlink(missing_ok=True)


def command_hosts(command):
    success = False
    for path in socket_dir().glob("host-*.sock"):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(str(path))
                client.sendall(command.encode("ascii"))
                success |= client.recv(16) == b"OK\n"
        except OSError:
            # A stale socket is harmless. Never unlink another process's socket.
            continue
    return success


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="restore hidden Thunderbird windows")
    parser.add_argument("--hide", action="store_true", help="hide Thunderbird windows")
    parser.add_argument("--quit", action="store_true", help="request a normal Thunderbird exit")
    args, _ = parser.parse_known_args()  # Firefox passes manifest path and add-on ID.
    commands = [name for name in ("show", "hide", "quit") if getattr(args, name)]
    if commands:
        return 0 if command_hosts(commands[0]) else 1
    Host().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
