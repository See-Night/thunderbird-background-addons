const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function harness(types = ["mail:3pane"], quiet = false, earlyStartup = false) {
  let cleanup;
  let watcher;
  const observers = new Map();
  const queue = [];
  const timers = new Map();
  const environment = new Map(quiet ? [["THUNDERBIRD_BACKGROUND_AUTOSTART", "1"]] : []);
  const displayCalls = [];
  const displayResult = {};
  const mailUtils = {
    displayMessageInFolderTab(...args) {
      displayCalls.push({ receiver: this, args, visible: windows.at(-1)?.base.visibility });
      return displayResult;
    },
  };
  const originalDisplayMessage = mailUtils.displayMessageInFolderTab;
  function createWindow(type = "mail:3pane") {
    const handlers = new Map();
    const base = { visibility: true };
    return {
      closed: false, windowState: 0, STATE_MINIMIZED: 1, base, focused: false,
      document: { documentElement: { getAttribute() { return type; } } },
      docShell: { treeOwner: { QueryInterface() { return base; } } },
      minimize() { this.windowState = 1; },
      restore() { this.windowState = 0; },
      focus() { this.focused = true; },
      goQuitApplication() { scope.Services.startup.quit(); },
      addEventListener(name, fn) { handlers.set(name, fn); },
      removeEventListener(name) { handlers.delete(name); },
      closeEvent() {
        const event = { target: this, prevented: false, stopped: false,
          preventDefault() { this.prevented = true; },
          stopImmediatePropagation() { this.stopped = true; } };
        handlers.get("close")?.(event);
        return event;
      },
      emit(name) { handlers.get(name)?.(); },
    };
  }
  const windows = types.map(createWindow);
  const scope = {
    ChromeUtils: { importESModule(name) {
      if (name.includes("MailUtils.sys.mjs")) { return { MailUtils: mailUtils }; }
      if (name.includes("Timer.sys.mjs")) {
        return { setTimeout(fn) { const id = {}; timers.set(id, fn); return id; },
          clearTimeout(id) { timers.delete(id); } };
      }
      return { ExtensionCommon: { ExtensionAPI: class {} } };
    } },
    Ci: { nsIBaseWindow: 1, nsISupportsPRBool: 2, nsIAppStartup: { eAttemptQuit: 3 } },
    console: { error() {} },
    Services: {
      env: { get(name) { return environment.get(name) || ""; },
        set(name, value) { environment.set(name, value); } },
      ww: { openWindow() {
        const win = createWindow();
        windows.push(win);
        watcher.onOpenWindow({ docShell: { domWindow: win } });
        return win;
      } },
      wm: {
        getEnumerator() { return windows.filter(w => !w.closed); },
        getMostRecentWindow() { return windows.findLast(w => !w.closed); },
        addListener(value) { watcher = value; }, removeListener() { watcher = null; },
      },
      obs: {
        addObserver(value, name) { observers.set(name, value); },
        removeObserver(value, name) { observers.delete(name); },
      },
      tm: { dispatchToMainThread(fn) { queue.push(fn); } },
      startup: { quit() {
        notifyQuit(false);
        observers.get("quit-application-granted")?.observe(null, "quit-application-granted");
      } },
    },
  };
  function notifyQuit(cancelled) {
    observers.get("quit-application-requested")?.observe({
      QueryInterface() { return { data: cancelled }; },
    }, "quit-application-requested");
  }
  vm.createContext(scope);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../addon/experiments/api.js"), "utf8"), scope);
  const instance = new scope.backgroundWindow();
  if (earlyStartup) { instance.onStartup(); }
  const api = instance.getAPI({ callOnClose(value) { cleanup = value; } }).backgroundWindow;
  return { api, windows, createWindow, observers, queue, notifyQuit, timers, environment,
    mailUtils, displayCalls, displayResult, originalDisplayMessage,
    cleanup: () => cleanup.close(), addWindow(win) {
      windows.push(win);
      watcher.onOpenWindow({ docShell: { domWindow: win } });
      if (win.document.documentElement.getAttribute("windowtype") === "mail:3pane") {
        observers.get("chrome-document-loaded").observe({
          documentURI: "chrome://messenger/content/messenger.xhtml", defaultView: win,
        });
      }
      win.emit("load");
    } };
}

test("X keeps the last main window alive and minimizes without a tray", async () => {
  const h = harness(); await h.api.start();
  const event = h.windows[0].closeEvent();
  assert.ok(event.prevented && event.stopped);
  assert.equal(h.windows[0].windowState, 1);
  assert.equal(h.windows[0].base.visibility, true);
});
test("tray hide, restore, and disappearance recover the window", async () => {
  const h = harness(); await h.api.start(); await h.api.setTrayAvailable(true);
  h.windows[0].closeEvent(); assert.equal(h.windows[0].base.visibility, false);
  await h.api.show(); assert.equal(h.windows[0].base.visibility, true);
  assert.ok(h.windows[0].focused);
  h.windows[0].closeEvent(); await h.api.setTrayAvailable(false);
  assert.equal(h.windows[0].base.visibility, true);
});
test("startup fallback does not focus an unrelated window", async () => {
  const h = harness(); await h.api.start(); await h.api.setTrayAvailable(false);
  assert.equal(h.windows[0].focused, false);
});
test("duplicate main windows close normally until only one remains", async () => {
  const h = harness(["mail:3pane", "mail:3pane"]); await h.api.start();
  assert.equal(h.windows[0].closeEvent().prevented, false);
  h.windows[0].closed = true;
  assert.equal(h.windows[1].closeEvent().prevented, true);
});
test("compose windows are untouched and newly opened main windows are handled", async () => {
  const h = harness([]); await h.api.start();
  const compose = h.createWindow("msgcompose"); h.addWindow(compose);
  assert.equal(compose.closeEvent().prevented, false);
  compose.closed = true;
  const main = h.createWindow(); h.addWindow(main);
  assert.equal(main.closeEvent().prevented, true);
});
test("Quit bypasses interception; cancelling Quit restores interception", async () => {
  const h = harness(); await h.api.start();
  h.notifyQuit(true);
  while (h.queue.length) { h.queue.shift()(); }
  assert.equal(h.windows[0].closeEvent().prevented, true);
  await h.api.quit();
  assert.equal(h.windows[0].closeEvent().prevented, false);
});
test("disabling restores hidden windows and removes interception", async () => {
  const h = harness(); await h.api.start(); await h.api.setTrayAvailable(true);
  h.windows[0].closeEvent(); h.cleanup();
  assert.equal(h.windows[0].base.visibility, true);
  assert.equal(h.windows[0].closeEvent().prevented, false);
  assert.equal(h.observers.size, 0);
});
test("tray Quit uses the application command and restores after a cancelled draft prompt", async () => {
  const h = harness(); await h.api.start(); await h.api.setTrayAvailable(true);
  h.windows[0].closeEvent();
  let called = false;
  h.windows[0].goQuitApplication = () => {
    called = true;
    h.notifyQuit(false); // A later native draft prompt can still cancel quitting.
  };
  await h.api.quit();
  assert.ok(called);
  assert.equal(h.windows[0].base.visibility, true);
  assert.equal(h.windows[0].closeEvent().prevented, true);
});
test("failed hiding falls back to minimizing", async () => {
  const h = harness(); await h.api.start(); await h.api.setTrayAvailable(true);
  Object.defineProperty(h.windows[0].base, "visibility", {
    get() { return true; }, set(value) { if (!value) { throw new Error("simulated unsupported hide"); } },
  });
  assert.equal(h.windows[0].closeEvent().prevented, true);
  assert.equal(h.windows[0].windowState, 1);
});
function openMailWindow(h) {
  const win = h.createWindow(); h.addWindow(win); return win;
}
test("quiet startup hides the normal mail window while the tray initializes", async () => {
  const h = harness([], true); await h.api.start();
  assert.equal(h.windows.length, 0);
  openMailWindow(h);
  assert.equal(h.windows.length, 1);
  assert.equal(h.windows[0].base.visibility, false);
  assert.equal(h.environment.get("THUNDERBIRD_BACKGROUND_AUTOSTART"), "");
  await h.api.setTrayAvailable(false);
  assert.equal(h.windows[0].base.visibility, false);
  h.windows[0].emit("load");
  await h.api.setTrayAvailable(true);
  assert.equal(h.timers.size, 0);
  assert.equal(h.windows[0].base.visibility, false);
  assert.equal(h.windows[0].focused, false);
  await h.api.show();
  assert.equal(h.windows[0].base.visibility, true);
});
test("silent startup falls back to minimized when the tray misses its deadline", async () => {
  const h = harness([], true); await h.api.start();
  openMailWindow(h);
  for (const callback of [...h.timers.values()]) { callback(); }
  assert.equal(h.windows[0].base.visibility, true);
  assert.equal(h.windows[0].windowState, 1);
  assert.equal(h.windows[0].focused, false);
});
test("showing the window during startup cancels later automatic hiding", async () => {
  const h = harness([], true); await h.api.start(); openMailWindow(h); await h.api.show();
  assert.equal(h.timers.size, 0);
  h.windows[0].emit("load");
  await h.api.setTrayAvailable(true);
  assert.equal(h.windows[0].base.visibility, true);
});
test("session-restored mail documents are hidden during quiet startup", async () => {
  const h = harness([], true); await h.api.start();
  const win = h.createWindow();
  h.observers.get("chrome-document-loaded").observe({
    documentURI: "chrome://messenger/content/messenger.xhtml", defaultView: win,
  });
  assert.equal(win.base.visibility, false);
  const compose = h.createWindow("msgcompose");
  h.observers.get("chrome-document-loaded").observe({
    documentURI: "chrome://messenger/content/messengercompose/messengercompose.xhtml", defaultView: compose,
  });
  assert.equal(compose.base.visibility, true);
});
test("the startup event initializes mail before the deferred extension background", async () => {
  const h = harness([], true, true);
  assert.equal(h.windows.length, 0);
  openMailWindow(h);
  assert.equal(h.windows.length, 1);
  assert.equal(h.windows[0].base.visibility, false);
  await h.api.start();
  assert.equal(h.windows.length, 1);
  assert.equal(h.timers.size, 1);
});
test("hidden startup runs mail initialization without waiting for a paint", async () => {
  const h = harness([], true, true);
  let initialized = 0;
  const win = h.createWindow();
  win.wrappedJSObject = { gMailInit: {
    _boundDelayedStartup: true,
    _delayedStartup() { initialized++; this._boundDelayedStartup = null; },
  } };
  h.addWindow(win);
  while (h.queue.length) { h.queue.shift()(); }
  assert.equal(initialized, 1);
  assert.equal(h.windows[0].base.visibility, false);
});
test("mail initialization waits for Thunderbird's asynchronous UI setup", async () => {
  const h = harness([], true, true);
  const win = openMailWindow(h);
  while (h.queue.length) { h.queue.shift()(); }
  let initialized = 0;
  win.wrappedJSObject = { gMailInit: {
    _boundDelayedStartup: true,
    _delayedStartup() { initialized++; this._boundDelayedStartup = null; },
  } };
  [...h.timers.values()].at(-1)();
  assert.equal(initialized, 1);
  assert.equal(win.base.visibility, false);
});
test("a native window created before the startup hook is still initialized", async () => {
  const h = harness([], true, true);
  const win = h.createWindow();
  h.windows.push(win); // The onOpenWindow event happened before our listener.
  h.observers.get("chrome-document-loaded").observe({
    documentURI: "chrome://messenger/content/messenger.xhtml", defaultView: win,
  });
  win.emit("load");
  assert.equal(win.base.visibility, false);
  assert.equal(win.closeEvent().prevented, true);
});
test("a notification restores the hidden window before dispatching its message", async () => {
  const h = harness(); await h.api.start(); await h.api.setTrayAvailable(true);
  const win = h.windows[0]; win.closeEvent();
  const message = { fixture: "notification-message" };
  const result = h.mailUtils.displayMessageInFolderTab(message, true);
  assert.equal(win.base.visibility, true);
  assert.ok(win.focused);
  assert.equal(result, h.displayResult);
  assert.equal(h.displayCalls.length, 1);
  assert.equal(h.displayCalls[0].receiver, h.mailUtils);
  assert.equal(h.displayCalls[0].args[0], message);
  assert.equal(h.displayCalls[0].args[1], true);
  assert.equal(h.displayCalls[0].visible, true);
});
test("notification restoration cancels pending quiet-start hiding", async () => {
  const h = harness([], true, true); const win = openMailWindow(h);
  h.mailUtils.displayMessageInFolderTab({}, true);
  assert.equal(h.timers.size, 0);
  win.emit("load");
  await h.api.setTrayAvailable(true);
  assert.equal(win.base.visibility, true);
});
test("visible windows and the no-main-window path retain the normal behavior", async () => {
  const h = harness(); await h.api.start();
  h.mailUtils.displayMessageInFolderTab({}, false);
  assert.equal(h.windows[0].focused, false);
  h.windows[0].closed = true;
  h.mailUtils.displayMessageInFolderTab({}, true);
  assert.equal(h.displayCalls.length, 2);
});
test("disabling removes the notification hook without clobbering other extensions", async () => {
  const h = harness(); await h.api.start(); h.cleanup();
  assert.equal(h.mailUtils.displayMessageInFolderTab, h.originalDisplayMessage);
  const other = harness(); await other.api.start();
  const wrapper = other.mailUtils.displayMessageInFolderTab;
  const laterWrapper = function (...args) { return wrapper.apply(this, args); };
  other.mailUtils.displayMessageInFolderTab = laterWrapper;
  other.cleanup();
  assert.equal(other.mailUtils.displayMessageInFolderTab, laterWrapper);
  other.mailUtils.displayMessageInFolderTab({}, true);
  assert.equal(other.displayCalls.length, 1);
});
