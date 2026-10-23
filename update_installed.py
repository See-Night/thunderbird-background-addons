#!/usr/bin/python3
"""Back up and update this local add-on, then restart Thunderbird normally."""
import argparse
import ctypes
import ctypes.util
import fcntl
import json
import os
import shlex
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

ADDON_ID = "background-local@thunderbird.local"
ROOT = Path(__file__).resolve().parent


def profile_pid(profile):
    try:
        return int(str((profile / "lock").readlink()).rsplit("+", 1)[1])
    except (OSError, ValueError, IndexError):
        return None


def belongs_to(pid, ancestor):
    for _ in range(10):
        if pid == ancestor:
            return True
        try:
            status = Path(f"/proc/{pid}/status").read_text()
            pid = int(next(line.split()[1] for line in status.splitlines() if line.startswith("PPid:")))
        except (OSError, ValueError, StopIteration):
            return False
        if pid <= 1:
            return False
    return False


def native_socket(profile):
    parent = profile_pid(profile)
    if parent is None:
        return None
    directory = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "thunderbird-background"
    for path in directory.glob("host-*.sock"):
        try:
            pid = int(path.stem.removeprefix("host-"))
        except ValueError:
            continue
        if belongs_to(pid, parent):
            return path
    return None


def take_lock(profile):
    lock = (profile / ".parentlock").open("r+b")
    try:
        fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock
    except BlockingIOError:
        lock.close()
        return None


def close_thunderbird(profile):
    lock = take_lock(profile)
    if lock is not None:
        return lock
    path = native_socket(profile)
    if path is None:
        raise RuntimeError("Cannot access the running Thunderbird native helper from this sandbox; no files changed")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(path))
        client.sendall(b"quit")
        if client.recv(16) != b"OK\n":
            raise RuntimeError("Thunderbird did not accept a normal Quit request")
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        lock = take_lock(profile)
        if lock is not None:
            return lock
        time.sleep(0.2)
    raise RuntimeError("Thunderbird is still open (possibly waiting for a draft confirmation); no files changed")


def cache_codec():
    library = ctypes.CDLL(ctypes.util.find_library("lz4"))

    def decode(data):
        if data[:8] != b"mozLz40\0":
            raise ValueError("Unrecognized add-on startup cache")
        size, = struct.unpack("<I", data[8:12])
        output = ctypes.create_string_buffer(size)
        if library.LZ4_decompress_safe(data[12:], output, len(data) - 12, size) != size:
            raise ValueError("Invalid add-on startup cache")
        return json.loads(output.raw)

    def encode(data):
        payload = json.dumps(data, separators=(",", ":")).encode()
        bound = library.LZ4_compressBound(len(payload))
        output = ctypes.create_string_buffer(bound)
        length = library.LZ4_compress_default(payload, output, len(payload), bound)
        if length <= 0:
            raise ValueError("Could not encode startup cache")
        return b"mozLz40\0" + struct.pack("<I", len(payload)) + output.raw[:length]

    return decode, encode


def atomic_write(path, data, mode):
    descriptor, temporary = tempfile.mkstemp(prefix=".thunderbird-background-update-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def desktop_environment():
    environment = dict(os.environ, THUNDERBIRD_BACKGROUND_AUTOSTART="1")
    keys = {"DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP"}
    result = subprocess.run(["systemctl", "--user", "show-environment"],
        capture_output=True, text=True, timeout=5, check=False)
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            values = shlex.split(line)
            if len(values) == 1 and "=" in values[0]:
                key, value = values[0].split("=", 1)
                if key in keys:
                    environment[key] = value
    if not environment.get("DISPLAY") and not environment.get("WAYLAND_DISPLAY"):
        runtime = Path(environment.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        for path in runtime.glob("wayland-*"):
            if path.is_socket():
                environment.update(WAYLAND_DISPLAY=path.name, MOZ_ENABLE_WAYLAND="1")
                break
    return environment


def update(profile, package):
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest["browser_specific_settings"]["gecko"]["id"] != ADDON_ID:
            raise ValueError("This updater only accepts the local Thunderbird background add-on")
        if archive.testzip() is not None:
            raise ValueError("Invalid XPI")
    decode, encode = cache_codec()
    with close_thunderbird(profile):
        target = profile / "extensions" / f"{ADDON_ID}.xpi"
        database_path = profile / "extensions.json"
        cache_path = profile / "addonStartup.json.lz4"
        database = json.loads(database_path.read_text())
        record = next(addon for addon in database["addons"] if addon["id"] == ADDON_ID)
        with zipfile.ZipFile(target) as archive:
            previous = json.loads(archive.read("manifest.json"))
        if previous.get("permissions") != manifest.get("permissions"):
            raise ValueError("Permission changes require installation through Thunderbird")
        cache = decode(cache_path.read_bytes())
        state = cache["app-profile"]["addons"][ADDON_ID]
        if not record["active"] or record["userDisabled"] or record["appDisabled"] or not state["enabled"]:
            raise ValueError("Refusing to change a disabled add-on")
        backup = Path.home() / ".local/share/thunderbird-background/backups" / datetime.now().strftime("%Y%m%d-%H%M%S-update")
        backup.mkdir(parents=True, mode=0o700)
        for path in (target, database_path, cache_path):
            shutil.copy2(path, backup / path.name)
        atomic_write(target, package.read_bytes(), 0o644)
        modified = target.stat().st_mtime_ns // 1_000_000
        record.update(version=manifest["version"], updateDate=modified)
        state.update(version=manifest["version"], lastModifiedTime=modified)
        if "telemetryKey" in state:
            state["telemetryKey"] = state["telemetryKey"].rsplit(":", 1)[0] + ":" + manifest["version"]
        try:
            atomic_write(database_path, json.dumps(database, separators=(",", ":")).encode(), 0o600)
            atomic_write(cache_path, encode(cache), 0o600)
        except BaseException:
            for path in (target, database_path, cache_path):
                shutil.copy2(backup / path.name, path)
            raise
        print(f"Updated {ADDON_ID}: {previous['version']} -> {manifest['version']}", flush=True)
        print(f"Backup: {backup}", flush=True)
    directory = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "thunderbird-background"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(directory / "autostart.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "ab") as log:
        log.write(f"\n{datetime.now().isoformat()} restart after add-on update\n".encode())
        log.flush()
        process = subprocess.Popen(["/usr/bin/thunderbird", "-profile", str(profile)],
            env=desktop_environment(), stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if native_socket(profile) is not None and take_lock(profile) is None:
            print("Thunderbird restarted and its native helper is running.", flush=True)
            return
        if process.poll() is not None:
            raise RuntimeError(f"Thunderbird exited after restart ({process.returncode}); see {directory / 'autostart.log'}")
        time.sleep(0.2)
    raise RuntimeError(f"Could not confirm restart; see {directory / 'autostart.log'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    update(args.profile.resolve(), args.package.resolve())
