#!/usr/bin/python3
"""Build the XPI and install the per-user Linux companion. No sudo needed."""
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
NAME = "local.thunderbird_background"
ADDON_ID = "background-local@thunderbird.local"


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
    thunderbird = shutil.which("thunderbird") or "/usr/bin/thunderbird"
    launcher = host.parent / "show.py"
    write_file(launcher, "#!/usr/bin/python3\nimport os, subprocess\n"
        f"if subprocess.run([{str(host)!r}, '--show'], check=False).returncode:\n"
        f"    os.execv({thunderbird!r}, [{thunderbird!r}])\n", 0o755)
    write_file(data / "applications/thunderbird-background.desktop",
        "[Desktop Entry]\nType=Application\nName=Thunderbird 后台运行\n"
        "Comment=打开或恢复 Thunderbird 窗口\n"
        f"Exec={desktop_quote(launcher)}\nIcon=org.mozilla.Thunderbird\nTerminal=false\n"
        "Categories=Network;Email;\nStartupNotify=true\n")
    print(f"本地托盘程序已安装：{host}")
    print(f"请在 Thunderbird 的“附加组件和主题 → 齿轮 → 从文件安装附加组件”中选择：\n{output}")
    print("扩展安装后才会生效。未修改邮件账户、Thunderbird 首选项或登录自启动设置。")


def uninstall():
    data, manifests = locations()
    for directory in manifests:
        (directory / f"{NAME}.json").unlink(missing_ok=True)
    (data / "applications/thunderbird-background.desktop").unlink(missing_ok=True)
    for name in ("host.py", "show.py", "autostart.py"):
        (data / "thunderbird-background" / name).unlink(missing_ok=True)
    (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) /
        "autostart/thunderbird-background.desktop").unlink(missing_ok=True)
    print("本地托盘程序和启动入口已移除。请在 Thunderbird 中移除“Thunderbird 后台运行”扩展。")


if __name__ == "__main__":
    if sys.argv[1:] == ["--uninstall"]:
        uninstall()
    elif sys.argv[1:] == ["--build-only"]:
        print(build())
    elif not sys.argv[1:]:
        install()
    else:
        sys.exit("Usage: install.py [--build-only|--uninstall]")
