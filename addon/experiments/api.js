/* Local Thunderbird 156 Experiment. No mail content is read or transmitted. */
var { ExtensionCommon } = ChromeUtils.importESModule(
  "resource://gre/modules/ExtensionCommon.sys.mjs"
);

var backgroundWindow = class extends ExtensionCommon.ExtensionAPI {
  onStartup() {
    // Register the quiet-start hooks before the normal mail window is loaded.
    if (Services.env.get("THUNDERBIRD_BACKGROUND_AUTOSTART") === "1") {
      this.getAPI(null).backgroundWindow.start().catch(console.error);
    }
  }

  onShutdown() {
    this._close?.();
  }

  getAPI(context) {
    if (this._api) {
      context?.callOnClose({ close: () => this._close() });
      return this._api;
    }
    const { setTimeout, clearTimeout } = ChromeUtils.importESModule(
      "resource://gre/modules/Timer.sys.mjs"
    );
    const handlers = new Map();
    const pending = new Map();
    const hidden = new Set();
    let available = false;
    let started = false;
    let quitting = false;
    let quitGranted = false;
    const startupWindows = new Set();
    const initializationTimers = new Map();
    let quietLaunch = false;
    let waitingForTray = false;
    let startupTimer = null;
    const stopQuietLaunch = () => {
      quietLaunch = false;
      waitingForTray = false;
      if (startupTimer !== null) { clearTimeout(startupTimer); startupTimer = null; }
      startupWindows.clear();
    };

    const windows = () => [...Services.wm.getEnumerator("mail:3pane")]
      .filter(win => !win.closed);
    const baseWindow = win => win.docShell.treeOwner.QueryInterface(Ci.nsIBaseWindow);
    const restore = win => {
      if (win.closed) {
        hidden.delete(win);
        return;
      }
      baseWindow(win).visibility = true;
      hidden.delete(win);
      if (win.windowState === win.STATE_MINIMIZED) {
        win.restore();
      }
      win.focus();
    };
    const show = () => {
      stopQuietLaunch();
      const candidates = [...hidden];
      if (!candidates.length) {
        const recent = Services.wm.getMostRecentWindow("mail:3pane");
        if (recent) {
          candidates.push(recent);
        }
      }
      for (const win of candidates) {
        try { restore(win); } catch (error) { console.error(error); }
      }
    };
    const hide = win => {
      if (!available) {
        win.minimize();
        return;
      }
      try {
        baseWindow(win).visibility = false;
        hidden.add(win);
      } catch (error) {
        console.error(error);
        // A failed hide must never make the main window inaccessible.
        try { baseWindow(win).visibility = true; } catch (_) {}
        win.minimize();
      }
    };
    const suppressStartupWindow = win => {
      startupWindows.add(win);
      try {
        // Before chrome loads this sets mShowAfterLoad=false, avoiding a flash.
        baseWindow(win).visibility = false;
        hidden.add(win);
      } catch (error) {
        console.error(error);
        win.minimize();
      }
    };
    const startupDocumentObserver = {
      observe(document) {
        if (quietLaunch && document.documentURI === "chrome://messenger/content/messenger.xhtml") {
          const win = document.defaultView;
          suppressStartupWindow(win);
          // The native window can be created before the Experiment's startup
          // event. In that case onOpenWindow was missed; still handle its load.
          if (!handlers.has(win) && !pending.has(win)) {
            const onLoad = () => { pending.delete(win); attach(win); };
            pending.set(win, onLoad);
            win.addEventListener("load", onLoad, { once: true });
          }
        }
      },
    };
    const initializeHiddenMail = win => {
      initializationTimers.delete(win);
      if (!started || win.closed) { return; }
      const chromeWindow = win.wrappedJSObject || win;
      if (chromeWindow.gMailInit?._boundDelayedStartup) {
        chromeWindow.gMailInit._delayedStartup();
        return;
      }
      if (chromeWindow.gMailInit?.delayedStartupFinished ||
          chromeWindow.gMailInit?._boundDelayedStartup === null) {
        return;
      }
      // Fluent/UI setup can finish after the window's load event. Wait until
      // Thunderbird has installed the paint listener before replacing it.
      initializationTimers.set(win, setTimeout(() => initializeHiddenMail(win), 50));
    };
    const attach = win => {
      if (handlers.has(win) || win.closed ||
          win.document.documentElement.getAttribute("windowtype") !== "mail:3pane") {
        return;
      }
      const onClose = event => {
        if (event.target !== win || quitting || windows().length > 1) {
          return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        hide(win);
      };
      const onUnload = () => {
        hidden.delete(win);
        handlers.delete(win);
      };
      win.addEventListener("close", onClose, true);
      win.addEventListener("unload", onUnload, { once: true });
      handlers.set(win, { onClose, onUnload });
      if (startupWindows.has(win)) {
        suppressStartupWindow(win);
        Services.tm.dispatchToMainThread(() => {
          if (win.closed || !startupWindows.has(win)) { return; }
          // Mirror Thunderbird's native start-in-tray path. A hidden window
          // never paints, so its MozAfterPaint listener cannot initialize mail.
          initializeHiddenMail(win);
        });
        // Session restoration opens its other windows before delayed startup ends.
        (win.wrappedJSObject || win).delayedStartupPromise?.then(() => { quietLaunch = false; });
      }
    };
    const listener = {
      onOpenWindow(xulWindow) {
        const win = xulWindow.docShell.domWindow;
        const onLoad = () => {
          pending.delete(win);
          attach(win);
        };
        pending.set(win, onLoad);
        win.addEventListener("load", onLoad, { once: true });
      },
      onCloseWindow() {},
      onWindowTitleChange() {},
    };
    // Quit, Ctrl+Q and session shutdown must bypass the close interception.
    const quitObserver = {
      observe(subject, topic) {
        if (topic === "quit-application-requested") {
          quitting = true;
          Services.tm.dispatchToMainThread(() => {
            if (!quitGranted) {
              quitting = false;
            }
          });
        } else if (topic === "quit-application-granted") {
          quitGranted = true;
          quitting = true;
        }
      },
    };
    const cleanup = {
      close() {
        if (!started) { return; }
        started = false;
        Services.wm.removeListener(listener);
        Services.obs.removeObserver(quitObserver, "quit-application-requested");
        Services.obs.removeObserver(quitObserver, "quit-application-granted");
        Services.obs.removeObserver(startupDocumentObserver, "chrome-document-loaded");
        stopQuietLaunch();
        for (const timer of initializationTimers.values()) { clearTimeout(timer); }
        initializationTimers.clear();
        for (const [win, onLoad] of pending) {
          win.removeEventListener("load", onLoad);
        }
        pending.clear();
        for (const [win, { onClose, onUnload }] of handlers) {
          win.removeEventListener("close", onClose, true);
          win.removeEventListener("unload", onUnload);
        }
        handlers.clear();
        // Disabling/uninstalling the add-on restores hidden windows.
        if (!quitting) { show(); }
      },
    };
    this._close = () => cleanup.close();
    context?.callOnClose(cleanup);
    return this._api = {
      backgroundWindow: {
        async start() {
          if (started) { return; }
          started = true;
          Services.wm.addListener(listener);
          Services.obs.addObserver(quitObserver, "quit-application-requested");
          Services.obs.addObserver(quitObserver, "quit-application-granted");
          Services.obs.addObserver(startupDocumentObserver, "chrome-document-loaded");
          if (Services.env.get("THUNDERBIRD_BACKGROUND_AUTOSTART") === "1") {
            Services.env.set("THUNDERBIRD_BACKGROUND_AUTOSTART", "");
            quietLaunch = true;
            waitingForTray = true;
            // A failed/missing tray host must not leave an unreachable window.
            startupTimer = setTimeout(() => {
              startupTimer = null;
              quietLaunch = false;
              waitingForTray = false;
              for (const win of startupWindows) {
                if (!win.closed) {
                  try {
                    // Set the minimized state BEFORE making the widget visible.
                    win.minimize();
                    baseWindow(win).visibility = true;
                    hidden.delete(win);
                  } catch (error) { console.error(error); }
                }
              }
              startupWindows.clear();
            }, 15000);
            const existing = windows();
            for (const win of existing) { suppressStartupWindow(win); }
          }
          // The normal command-line handler creates the window. Creating it
          // here as well races the handler and opens duplicate mail windows.
          for (const win of windows()) { attach(win); }
        },
        async setTrayAvailable(value) {
          available = value;
          if (available && waitingForTray) {
            waitingForTray = false;
            if (startupTimer !== null) { clearTimeout(startupTimer); startupTimer = null; }
          }
          if (!available && !waitingForTray && hidden.size) { show(); }
        },
        async show() { show(); },
        async hide() {
          for (const win of windows()) { hide(win); }
        },
        async quit() {
          // Use Thunderbird's own quit command, including its observer checks.
          // Restore the main window so confirmation dialogs have a visible parent.
          show();
          const win = Services.wm.getMostRecentWindow("mail:3pane");
          try {
            const chromeWindow = win && (win.wrappedJSObject || win);
            if (chromeWindow?.goQuitApplication) {
              chromeWindow.goQuitApplication();
            } else {
              const cancelled = Cc["@mozilla.org/supports-PRBool;1"]
                .createInstance(Ci.nsISupportsPRBool);
              Services.obs.notifyObservers(cancelled, "quit-application-requested");
              if (!cancelled.data) {
                Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit);
              }
            }
          } finally {
            if (!quitGranted) { quitting = false; }
          }
        },
      },
    };
  }
};
