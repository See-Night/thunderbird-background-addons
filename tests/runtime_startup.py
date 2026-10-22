#!/usr/bin/python3
"""Run actual Thunderbird with a disposable local-only account and no desktop."""
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="thunderbird-background-runtime-") as directory:
        profile = Path(directory)
        (profile / "extensions").mkdir()
        language_pack = os.environ.get("TBBG_TEST_LANGUAGE_XPI")
        if language_pack:
            shutil.copy2(language_pack, profile / "extensions" / Path(language_pack).name)
        (profile / "Mail/Local Folders").mkdir(parents=True)
        preferences = {
            "extensions.autoDisableScopes": 0,
            "extensions.startupScanScopes": 15,
            "extensions.sideloadScopes": 15,
            "devtools.console.stdout.chrome": True,
            "mail.accountmanager.accounts": "account1",
            "mail.accountmanager.localfoldersserver": "server1",
            "mail.account.account1.server": "server1",
            "mail.server.server1.type": "none",
            "mail.server.server1.hostname": "Local Folders",
            "mail.server.server1.userName": "nobody",
            "mail.server.server1.name": "Local Folders",
            "mail.server.server1.directory": str(profile / "Mail/Local Folders"),
            "mail.provider.suppress_dialog_on_startup": True,
            "mail.shell.checkDefaultClient": False,
        }
        (profile / "user.js").write_text("\n".join(
            f"user_pref({json.dumps(k)}, {json.dumps(v)});" for k, v in preferences.items()))
        result_file = profile / "runtime-result.json"
        probe = """  onStartup() {
    const { setTimeout } = ChromeUtils.importESModule('resource://gre/modules/Timer.sys.mjs');
    setTimeout(async () => {
      const windows = [...Services.wm.getEnumerator('mail:3pane')].map(win => {
        const chromeWindow = win.wrappedJSObject || win;
        return {ready: win.document.readyState,
          initialized: !!chromeWindow.gMailInit?.delayedStartupFinished,
          bound: !!chromeWindow.gMailInit?._boundDelayedStartup,
          stats: this._testStats?.(win),
          hidden: this._testHidden?.has(win) === true};
      });
      await IOUtils.writeJSON(RESULT_PATH, {windows});
    }, 8000);
""".replace("RESULT_PATH", json.dumps(str(result_file)))
        addon = profile / "extensions/background-local@thunderbird.local.xpi"
        with zipfile.ZipFile(addon, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in (ROOT / "addon").rglob("*"):
                if not path.is_file():
                    continue
                content = path.read_text()
                if path.name == "api.js":
                    content = content.replace("  onStartup() {", probe, 1)
                    content = content.replace("const hidden = new Set();",
                                              "const hidden = new Set(); this._testHidden = hidden; this._testStats = win => ({attached: handlers.has(win), pending: pending.has(win), startup: startupWindows.has(win)});", 1)
                archive.writestr(str(path.relative_to(ROOT / "addon")), content)
        environment = dict(os.environ, MOZ_HEADLESS="1", THUNDERBIRD_BACKGROUND_AUTOSTART="1")
        for mode in ("initial", "registered"):
            if mode == "registered":
                with (profile / "user.js").open("a") as prefs:
                    prefs.write('\nuser_pref("extensions.startupScanScopes", 4);\n'
                                'user_pref("extensions.sideloadScopes", 0);\n'
                                'user_pref("extensions.autoDisableScopes", 15);\n')
                result_file.unlink(missing_ok=True)
            print(f"Checking {mode} startup", flush=True)
            with (profile / "runtime.log").open("w") as log:
                process = subprocess.Popen(["/usr/bin/thunderbird", "-no-remote", "-profile", str(profile)],
                    env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    deadline = time.monotonic() + 20
                    while not result_file.exists() and time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise AssertionError(f"Thunderbird exited early ({process.returncode})")
                        time.sleep(0.1)
                    if not result_file.exists():
                        raise AssertionError("No runtime result from Thunderbird")
                    result = json.loads(result_file.read_text())
                    print(json.dumps(result, ensure_ascii=False))
                    assert len(result["windows"]) == 1, "Expected exactly one mail window"
                    assert all(result["windows"][0][key] == value for key, value in
                        {"ready": "complete", "initialized": True, "hidden": True}.items())
                    print("Actual Thunderbird startup: one hidden, initialized mail window — PASS")
                    capture = os.environ.get("TBBG_TEST_CAPTURE")
                    if capture:
                        destination = Path(capture)
                        destination.mkdir(parents=True, exist_ok=True)
                        for name in ("extensions.json", "addonStartup.json.lz4"):
                            shutil.copy2(profile / name, destination / name)
                except BaseException:
                    print((profile / "runtime.log").read_text()[-6500:])
                    raise
                finally:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()


if __name__ == "__main__":
    main()
