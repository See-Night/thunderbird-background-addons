// Injected only into the disposable Thunderbird runtime test.
async function checkNotificationClick(api) {
  const { MailServices } = ChromeUtils.importESModule("resource:///modules/MailServices.sys.mjs");
  const { MailNotificationManager } = ChromeUtils.importESModule("resource:///modules/MailNotificationManager.sys.mjs");
  const { setTimeout } = ChromeUtils.importESModule("resource://gre/modules/Timer.sys.mjs");
  const win = Services.wm.getMostRecentWindow("mail:3pane");
  const chromeWindow = win.wrappedJSObject || win;
  const hiddenBefore = api._testHidden.has(win);

  const root = MailServices.accounts.localFoldersServer.rootFolder;
  let folder;
  try { folder = root.getChildNamed("Notification fixture"); } catch (_) {}
  if (!folder) {
    root.createSubfolder("Notification fixture", null);
    folder = root.getChildNamed("Notification fixture");
  }
  const header = folder.QueryInterface(Ci.nsIMsgLocalMailFolder).addMessage(
    "From - Thu Oct 22 00:00:00 2026\r\n" +
    "From: fixture@example.invalid\r\nTo: local@example.invalid\r\n" +
    "Subject: Notification restore fixture\r\nMessage-ID: <tray-fixture@example.invalid>\r\n" +
    "Date: Thu, 22 Oct 2026 00:00:00 +0000\r\n\r\nLocal test message.\r\n"
  );
  let callbacks = null;
  const service = {
    QueryInterface: ChromeUtils.generateQI(["nsIAlertsService"]),
    showAlertWithCallbacks(_alert, listener) { callbacks = listener; },
  };
  const factory = {
    QueryInterface: ChromeUtils.generateQI(["nsIFactory"]),
    createInstance(...args) { return service.QueryInterface(args.at(-1)); },
  };
  // Capture the real mail notification's click callback without posting a
  // desktop alert. The replacement exists only in this disposable process.
  Components.manager.QueryInterface(Ci.nsIComponentRegistrar).registerFactory(
    Services.uuid.generateUUID(), "Notification fixture alerts", "@mozilla.org/system-alerts-service;1", factory
  );
  const about3Pane = chromeWindow.document.getElementById("tabmail").currentAbout3Pane;
  about3Pane.paneLayout.messagePaneVisible = true;
  MailNotificationManager._showAlert(header, "Test notification", "Local fixture", 2);
  if (!callbacks) { throw new Error("Mail notification did not register its callback"); }
  callbacks.onAlertClick(null);

  let selectedMessageCorrect = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    const selected = about3Pane.gDBView?.hdrForFirstSelectedMessage;
    if (selected?.messageKey === header.messageKey && selected.folder.URI === folder.URI) {
      selectedMessageCorrect = true;
      break;
    }
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  return { hiddenBefore, hiddenAfter: api._testHidden.has(win), selectedMessageCorrect };
}
