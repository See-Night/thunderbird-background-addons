#!/usr/bin/python3
"""Build the XPI and install the per-user Linux companion. No sudo needed."""
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "local.thunderbird_background"
ADDON_ID = "background-local@thunderbird.local"
DESKTOP_ID = "org.mozilla.Thunderbird.desktop"
DOCK_MARKER = "X-Thunderbird-Background"


def locations():
    home = Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    # XREUserNativeManifests uses the shared Mozilla directory, including in TB.
    return data, [home / ".mozilla/native-messaging-hosts",
                  config / "mozilla/native-messaging-hosts"]


def write_file(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def build():
    version = json.loads((ROOT / "addon/manifest.json").read_text())["version"]
    output = ROOT / f"dist/thunderbird-background-{version}.xpi"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "addon").rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT / "addon"))
    return output


def desktop_quote(value):
    # Desktop Entry Exec quoting is different from shell quoting.
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%") + '"'


def desktop_keyfile(path):
    from gi.repository import GLib  # pyright: ignore[reportMissingModuleSource]
    entry = GLib.KeyFile()
    entry.load_from_file(str(path), GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    return entry


def managed_desktop(path):
    from gi.repository import GLib  # pyright: ignore[reportMissingModuleSource]
    if not path.is_file():
        return False
    try:
        return desktop_keyfile(path).get_boolean("Desktop Entry", DOCK_MARKER)
    except GLib.Error:
        return False


def install_dock_entry(data, launcher):
    target = data / "applications" / DESKTOP_ID
    backup = launcher.parent / "dock-original.desktop"
    if target.exists() and not managed_desktop(target):
        if backup.exists():
            raise RuntimeError(f"Existing launcher and backup preserved; check these files first: {target}, {backup}")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    source = backup if backup.exists() else None
    if source is None:
        for directory in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
            if directory:
                candidate = Path(directory) / "applications" / DESKTOP_ID
                if candidate.is_file() and candidate != target:
                    source = candidate
                    break
    if source is None:
        print('No native Thunderbird desktop entry found; keeping the separate "Thunderbird Background" entry.')
        return
    entry = desktop_keyfile(source)
    entry.set_string("Desktop Entry", "Exec", f"{desktop_quote(launcher)} %u")
    entry.set_boolean("Desktop Entry", "DBusActivatable", False)
    # Restoring an existing window does not complete a new startup sequence.
    entry.set_boolean("Desktop Entry", "StartupNotify", False)
    entry.set_boolean("Desktop Entry", DOCK_MARKER, True)
    write_file(target, entry.to_data()[0])
    print(f"Dock restore entry installed: {target}")


def uninstall_dock_entry(data):
    target = data / "applications" / DESKTOP_ID
    backup = data / "thunderbird-background/dock-original.desktop"
    if managed_desktop(target):
        if backup.exists():
            shutil.copy2(backup, target)
            backup.unlink()
        else:
            target.unlink()


def install():
    import gi
    gi.require_version("Gio", "2.0")
    output = build()
    data, manifests = locations()
    host = data / "thunderbird-background/host.py"
    write_file(host, (ROOT / "native/host.py").read_text(), 0o755)
    write_file(host.parent / "autostart.py", (ROOT / "native/autostart.py").read_text(), 0o755)
    manifest = json.dumps({"name": NAME, "description": "Local Thunderbird background tray",
        "path": str(host), "type": "stdio", "allowed_extensions": [ADDON_ID]}, indent=2) + "\n"
    for directory in manifests:
        write_file(directory / f"{NAME}.json", manifest)
    launcher = host.parent / "show.py"
    write_file(launcher, (ROOT / "native/show.py").read_text(), 0o755)
    write_file(data / "applications/thunderbird-background.desktop",
        "[Desktop Entry]\nType=Application\nName=Thunderbird Background\n"
        "Comment=Open or restore Thunderbird windows\n"
        f"Exec={desktop_quote(launcher)}\nIcon=org.mozilla.Thunderbird\nTerminal=false\n"
        "Categories=Network;Email;\nStartupNotify=false\n")
    install_dock_entry(data, launcher)
    print(f"Local tray companion installed: {host}")
    print(f"In Thunderbird, open Add-ons and Themes -> gear icon -> Install Add-on From File, and select:\n{output}")
    print("Changes take effect after installing the extension. Mail accounts, Thunderbird preferences, and login autostart settings were not modified.")


def uninstall():
    data, manifests = locations()
    uninstall_dock_entry(data)
    for directory in manifests:
        (directory / f"{NAME}.json").unlink(missing_ok=True)
    (data / "applications/thunderbird-background.desktop").unlink(missing_ok=True)
    for name in ("host.py", "show.py", "autostart.py"):
        (data / "thunderbird-background" / name).unlink(missing_ok=True)
    (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) /
        "autostart/thunderbird-background.desktop").unlink(missing_ok=True)
    print('Local tray companion and launch entries removed. Remove the "Thunderbird Background" extension in Thunderbird.')


if __name__ == "__main__":
    if sys.argv[1:] == ["--uninstall"]:
        uninstall()
    elif sys.argv[1:] == ["--build-only"]:
        print(build())
    elif not sys.argv[1:]:
        install()
    else:
        sys.exit("Usage: install.py [--build-only|--uninstall]")
