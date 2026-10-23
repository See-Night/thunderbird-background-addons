"""Exercise launch completion against a local Wayland protocol peer."""
import importlib.util
import socket
import struct
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("startup_launcher", ROOT / "native/show.py")
if spec is None or spec.loader is None:
    raise ImportError("Cannot load the startup launcher")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def wire_string(value):
    data = value.encode() + b"\0"
    return struct.pack("=I", len(data)) + data + b"\0" * (-len(data) % 4)


def read_message(client):
    def read_exact(size):
        data = bytearray()
        while len(data) < size:
            part = client.recv(size - len(data))
            if not part:
                raise EOFError
            data.extend(part)
        return bytes(data)
    object_id, header = struct.unpack("=II", read_exact(8))
    return object_id, header & 65535, read_exact((header >> 16) - 8)


class StartupTests(unittest.TestCase):
    def peer(self, server, advertise_shell):
        with server.accept()[0] as client:
            client.settimeout(3)
            registry = None
            shell = None
            tokens = []
            while True:
                object_id, opcode, payload = read_message(client)
                if object_id == 1 and opcode == 1:  # get_registry
                    registry, = struct.unpack("=I", payload)
                elif object_id == 1 and opcode == 0:  # sync
                    callback, = struct.unpack("=I", payload)
                    if shell is None and advertise_shell:
                        event = struct.pack("=I", 42) + wire_string("gtk_shell1") + struct.pack("=I", 1)
                        # Fragment the event so the client cannot assume full reads.
                        data = struct.pack("=II", registry, (8 + len(event)) << 16) + event
                        client.sendall(data[:5])
                        client.sendall(data[5:])
                    client.sendall(struct.pack("=III", callback, 12 << 16, 0))
                    if shell is not None or not advertise_shell:
                        return tokens
                elif object_id == registry and opcode == 0:  # bind
                    self.assertEqual(payload[:4], struct.pack("=I", 42))
                    self.assertEqual(payload[4:-8], wire_string("gtk_shell1"))
                    version, shell = struct.unpack("=II", payload[-8:])
                    self.assertEqual(version, 1)
                elif object_id == shell and opcode == 1:  # set_startup_id
                    length, = struct.unpack_from("=I", payload)
                    tokens.append(payload[4:4 + length - 1].decode())
                else:
                    self.fail(f"Unexpected Wayland request: {object_id}, {opcode}")

    def test_restore_completes_both_wayland_and_legacy_launch_ids(self):
        for legacy in ("legacy-launch_TIME123", "activation_TIME123"):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as directory:
                path = str(Path(directory) / "wayland-test")
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(path)
                    server.listen(1)
                    server.settimeout(3)
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        result = pool.submit(self.peer, server, True)
                        with patch.dict(launcher.os.environ, {
                            "WAYLAND_DISPLAY": path,
                            "XDG_ACTIVATION_TOKEN": "activation_TIME123",
                            "DESKTOP_STARTUP_ID": legacy,
                        }), patch.object(launcher.subprocess, "run") as run, \
                                patch.object(launcher.os, "execv") as execute:
                            run.return_value.returncode = 0
                            self.assertEqual(launcher.main([]), 0)
                            execute.assert_not_called()
                        self.assertEqual(result.result(timeout=3), list(dict.fromkeys([
                            "activation_TIME123", legacy,
                        ])))

    def test_compositor_without_gnome_shell_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "wayland-test")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(path)
                server.listen(1)
                server.settimeout(3)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(self.peer, server, False)
                    with patch.dict(launcher.os.environ, {"WAYLAND_DISPLAY": path}):
                        self.assertFalse(launcher.complete_wayland_startup(["launch_TIME123"]))
                    self.assertEqual(result.result(timeout=3), [])

    def test_terminal_restore_does_not_connect_to_the_display(self):
        with patch.dict(launcher.os.environ, {"XDG_ACTIVATION_TOKEN": "", "DESKTOP_STARTUP_ID": ""}), \
                patch.object(launcher.socket, "socket") as connect:
            self.assertFalse(launcher.complete_startup())
            connect.assert_not_called()

    def test_missing_display_does_not_break_window_restoration(self):
        with patch.dict(launcher.os.environ, {
            "XDG_ACTIVATION_TOKEN": "launch_TIME123",
            "WAYLAND_DISPLAY": "", "DISPLAY": "",
        }), patch.object(launcher.subprocess, "run") as run, \
                patch.object(launcher.os, "execv") as execute:
            run.return_value.returncode = 0
            self.assertEqual(launcher.main([]), 0)
            execute.assert_not_called()

    def test_display_failure_does_not_break_window_restoration(self):
        with patch.dict(launcher.os.environ, {
            "XDG_ACTIVATION_TOKEN": "launch_TIME123", "WAYLAND_DISPLAY": "/missing/wayland-test",
        }), patch.object(launcher.subprocess, "run") as run, \
                patch.object(launcher.os, "execv") as execute:
            run.return_value.returncode = 0
            self.assertEqual(launcher.main([]), 0)
            execute.assert_not_called()

    def test_fresh_launch_leaves_notification_for_thunderbird(self):
        with patch.object(launcher.subprocess, "run") as run, \
                patch.object(launcher, "complete_startup") as complete, \
                patch.object(launcher.shutil, "which", return_value="/usr/bin/thunderbird"), \
                patch.object(launcher.os, "execv") as execute:
            run.return_value.returncode = 1
            launcher.main([])
            complete.assert_not_called()
            execute.assert_called_once_with("/usr/bin/thunderbird", ["/usr/bin/thunderbird"])


if __name__ == "__main__":
    unittest.main()
