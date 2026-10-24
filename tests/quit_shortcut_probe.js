async function checkQuitShortcut(extension) {
  const api = extension.getAPI(null).backgroundWindow;
  const win = Services.wm.getMostRecentWindow("mail:3pane");
  const key = win.document.getElementById("key_quitApplication");
  const command = win.document.getElementById("cmd_quitApplication");
  const menuHandler = command.getAttribute("oncommand");
  let quitRequests = 0;
  let trustedKeyEvents = 0;
  const cancelQuit = {
    observe(subject) {
      quitRequests++;
      subject.QueryInterface(Ci.nsISupportsPRBool).data = true;
    },
  };
  const onKey = event => {
    if (event.isTrusted && event.ctrlKey && event.key.toLowerCase() === "q") {
      trustedKeyEvents++;
    }
  };
  Services.obs.addObserver(cancelQuit, "quit-application-requested");
  win.addEventListener("keydown", onKey, true);
  try {
    const eventUtils = { window: win, parent: win, _EU_Ci: Ci, _EU_Cc: Cc };
    Services.scriptloader.loadSubScript(
      "chrome://remote/content/external/EventUtils.js", eventUtils
    );
    await api.setTrayAvailable(true);
    await api.show();
    key.doCommand();
    const commandHidesWithTray = extension._testHidden.has(win);
    await api.show();
    if (!eventUtils._getTIP(win)) {
      throw new Error("TextInputProcessor is unavailable for the shortcut test");
    }
    eventUtils.synthesizeKey("q", { ctrlKey: true, code: "KeyQ" }, win);
    const keyboardHidesWithTray = extension._testHidden.has(win);
    await api.show();
    await api.setTrayAvailable(false);
    eventUtils.synthesizeKey("q", { ctrlKey: true, code: "KeyQ" }, win);
    const keyboardMinimizesWithoutTray = win.windowState === win.STATE_MINIMIZED;
    const shortcutQuitRequests = quitRequests;
    await api.show();
    command.doCommand();
    const menuRequestsQuit = quitRequests === 1;
    await new Promise(resolve => Services.tm.dispatchToMainThread(resolve));
    extension.onShutdown();
    const restored = key.getAttribute("command") === "cmd_quitApplication";
    key.doCommand();
    const restoredShortcutRequestsQuit = quitRequests === 2;
    return {
      commandHidesWithTray, keyboardHidesWithTray, keyboardMinimizesWithoutTray,
      shortcutQuitRequests, menuRequestsQuit, restored, restoredShortcutRequestsQuit,
      menuUnchanged: command.getAttribute("oncommand") === menuHandler,
      trustedKeyEvents,
    };
  } finally {
    win.removeEventListener("keydown", onKey, true);
    Services.obs.removeObserver(cancelQuit, "quit-application-requested");
  }
}
