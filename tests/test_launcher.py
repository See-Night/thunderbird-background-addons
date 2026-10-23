import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load("launcher", ROOT / "native/show.py")
installer = load("installer", ROOT / "install.py")
DESKTOP = """[Desktop Entry]
Name=Thunderbird
Name[zh_CN]=雷鸟
Exec=thunderbird %u
Type=Application
DBusActivatable=true
MimeType=x-scheme-handler/mailto;
StartupWMClass=thunderbird
Actions=ComposeMessage;OpenAddressBook;

[Desktop Action ComposeMessage]
Name=Compose
Exec=thunderbird -compose

[Desktop Action OpenAddressBook]
Name=Address book
Exec=thunderbird -addressbook
"""


class LauncherTests(unittest.TestCase):
    def test_dock_click_restores_existing_window_without_launching_again(self):
        with patch.object(launcher.subprocess, "run") as run, patch.object(launcher.os, "execv") as execute:
            run.return_value.returncode = 0
            self.assertEqual(launcher.main([]), 0)
            self.assertEqual(run.call_args.args[0][-1], "--show")
            execute.assert_not_called()

    def test_missing_disconnected_or_stuck_host_falls_back_to_normal_startup(self):
        for error in (None, FileNotFoundError(), subprocess.TimeoutExpired("host", 5)):
            with self.subTest(error=error), patch.object(launcher.subprocess, "run") as run, \
                    patch.object(launcher.shutil, "which", return_value="/usr/bin/thunderbird"), \
                    patch.object(launcher.os, "execv") as execute:
                run.return_value.returncode = 1
                run.side_effect = error
                launcher.main([])
                execute.assert_called_once_with("/usr/bin/thunderbird", ["/usr/bin/thunderbird"])

    def test_explicit_arguments_reach_thunderbird_unchanged(self):
        for arguments in (["mailto:person@example.invalid?subject=hello%20world"],
                          ["-compose", "subject='hello world'"], ["-addressbook"], ["/tmp/mail with spaces.eml"]):
            with self.subTest(arguments=arguments), patch.object(launcher.subprocess, "run") as run, \
                    patch.object(launcher.shutil, "which", return_value="/usr/bin/thunderbird"), \
                    patch.object(launcher.os, "execv") as execute:
                launcher.main(arguments)
                run.assert_not_called()
                execute.assert_called_once_with("/usr/bin/thunderbird", ["/usr/bin/thunderbird", *arguments])


class DesktopTests(unittest.TestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        # unittest calls setUp before each test to initialize these fixtures.
        self.temp: tempfile.TemporaryDirectory[str]
        self.data: Path
        self.system: Path
        self.launcher: Path
        self.target: Path
        self.backup: Path

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="thunderbird-dock-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.data = root / "user data"
        self.system = root / "system"
        original = self.system / "applications" / installer.DESKTOP_ID
        original.parent.mkdir(parents=True)
        original.write_text(DESKTOP)
        self.launcher = self.data / "thunderbird-background/show.py"
        self.target = self.data / "applications" / installer.DESKTOP_ID
        self.backup = self.launcher.parent / "dock-original.desktop"
        environment = patch.dict(installer.os.environ, {"XDG_DATA_DIRS": str(self.system)})
        environment.start()
        self.addCleanup(environment.stop)

    def test_original_dock_identity_actions_and_translations_are_preserved(self):
        installer.install_dock_entry(self.data, self.launcher)
        entry = installer.desktop_keyfile(self.target)
        self.assertEqual(entry.get_string("Desktop Entry", "Exec"), f'"{self.launcher}" %u')
        self.assertFalse(entry.get_boolean("Desktop Entry", "DBusActivatable"))
        self.assertEqual(entry.get_string("Desktop Entry", "Name[zh_CN]"), "雷鸟")
        self.assertEqual(entry.get_string("Desktop Entry", "StartupWMClass"), "thunderbird")
        self.assertEqual(entry.get_string("Desktop Action ComposeMessage", "Exec"), "thunderbird -compose")
        self.assertEqual(entry.get_string("Desktop Action OpenAddressBook", "Exec"), "thunderbird -addressbook")
        installer.uninstall_dock_entry(self.data)
        self.assertFalse(self.target.exists())

    def test_custom_entry_is_backed_up_once_and_restored_on_uninstall(self):
        self.target.parent.mkdir(parents=True)
        original = DESKTOP.replace("Name=Thunderbird", "Name=Custom Thunderbird")
        self.target.write_text(original)
        installer.install_dock_entry(self.data, self.launcher)
        installer.install_dock_entry(self.data, self.launcher)
        self.assertEqual(self.backup.read_text(), original)
        installer.uninstall_dock_entry(self.data)
        self.assertEqual(self.target.read_text(), original)
        self.assertFalse(self.backup.exists())

    def test_uninstall_preserves_a_subsequently_replaced_user_entry(self):
        installer.install_dock_entry(self.data, self.launcher)
        self.target.write_text(DESKTOP)
        installer.uninstall_dock_entry(self.data)
        self.assertEqual(self.target.read_text(), DESKTOP)


if __name__ == "__main__":
    unittest.main()
