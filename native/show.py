#!/usr/bin/python3
"""Restore a background window, or start Thunderbird with the supplied arguments."""
import os
import shutil
import socket
import struct
import subprocess
import sys
from pathlib import Path


def complete_startup():
    """Complete this launch after restoring a window owned by another process."""
    tokens = list(dict.fromkeys(filter(None, (
        os.environ.get("XDG_ACTIVATION_TOKEN"),
        os.environ.get("DESKTOP_STARTUP_ID"),
    ))))
    if not tokens:
        return False
    try:
        if os.environ.get("WAYLAND_DISPLAY"):
            return complete_wayland_startup(tokens)
        display_name = os.environ.get("DISPLAY")
        if not display_name:
            return False
        import gi
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk  # pyright: ignore[reportMissingModuleSource]
        display = Gdk.Display.open(display_name)
        if display is None:
            return False
        try:
            for token in tokens:
                display.notify_startup_complete(token)
            display.sync()
        finally:
            display.close()
        return True
    except (OSError, ValueError, ImportError) as error:
        print(f"Thunderbird startup notification: {error}", file=sys.stderr)
        return False


def complete_wayland_startup(tokens):
    # GTK's public completion API is a no-op when xdg_activation_v1 exists.
    # GNOME's gtk_shell1 v1 provides a completion request without a new surface.
    # Only core registry/sync and gtk_shell1.set_startup_id are needed; none of
    # these messages transfer file descriptors or create visible windows.
    display_name = os.environ["WAYLAND_DISPLAY"]
    path = Path(display_name)
    if not path.is_absolute():
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime:
            return False
        path = Path(runtime) / path

    def string(value):
        encoded = value.encode("utf-8") + b"\0"
        return struct.pack("=I", len(encoded)) + encoded + b"\0" * (-len(encoded) % 4)

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        connection.connect(str(path))

        def send(object_id, opcode, payload=b""):
            size = 8 + len(payload)
            if size > 65535:
                raise ValueError("startup notification is too large")
            connection.sendall(struct.pack("=II", object_id, size << 16 | opcode) + payload)

        def read_exact(size):
            data = bytearray()
            while len(data) < size:
                chunk = connection.recv(size - len(data))
                if not chunk:
                    raise OSError("Wayland connection closed")
                data.extend(chunk)
            return bytes(data)

        def roundtrip(callback):
            send(1, 0, struct.pack("=I", callback))  # wl_display.sync
            shell_name = None
            while True:
                object_id, header = struct.unpack("=II", read_exact(8))
                size, opcode = header >> 16, header & 65535
                if size < 8 or size % 4:
                    raise ValueError("invalid Wayland event")
                payload = read_exact(size - 8)
                if object_id == 1 and opcode == 0:  # wl_display.error
                    raise OSError("Wayland rejected startup notification")
                if object_id == 2 and opcode == 0:  # wl_registry.global
                    name, length = struct.unpack_from("=II", payload)
                    if payload[8:8 + length] == b"gtk_shell1\0":
                        shell_name = name
                if object_id == callback and opcode == 0:
                    return shell_name

        send(1, 1, struct.pack("=I", 2))  # wl_display.get_registry
        name = roundtrip(3)
        if name is None:
            return False
        send(2, 0, struct.pack("=I", name) + string("gtk_shell1") + struct.pack("=II", 1, 4))
        for token in tokens:
            send(4, 1, string(token))  # gtk_shell1.set_startup_id
        roundtrip(5)  # Wait until the compositor has processed completion.
        return True


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else list(arguments)
    if not arguments:
        host = Path(__file__).resolve().with_name("host.py")
        try:
            result = subprocess.run([str(host), "--show"], check=False, timeout=5)
            if result.returncode == 0:
                complete_startup()
                return 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Preserve mailto URLs, files, -compose and other explicit launch requests.
    thunderbird = shutil.which("thunderbird") or "/usr/bin/thunderbird"
    os.execv(thunderbird, [thunderbird, *arguments])


if __name__ == "__main__":
    sys.exit(main())
