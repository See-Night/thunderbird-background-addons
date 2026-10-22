/* Only command names cross the native messaging connection. */
let port = null;
let retry = null;
const api = browser.backgroundWindow;

function connect() {
  try {
    const connection = browser.runtime.connectNative("local.thunderbird_background");
    port = connection;
    connection.onMessage.addListener(async message => {
      if (port !== connection) { return; }
      try {
        switch (message.action) {
          case "tray": await api.setTrayAvailable(message.available === true); break;
          case "show": await api.show(); break;
          case "hide": await api.hide(); break;
          case "quit": await api.quit(); break;
        }
      } catch (error) { console.error("Thunderbird background:", error); }
    });
    connection.onDisconnect.addListener(() => {
      if (port !== connection) { return; }
      port = null;
      console.warn("Thunderbird background native host disconnected.",
        browser.runtime.lastError?.message || "");
      api.setTrayAvailable(false).catch(console.error);
      retry = setTimeout(connect, 10000);
    });
  } catch (error) {
    console.error(error);
    api.setTrayAvailable(false).catch(console.error);
    retry = setTimeout(connect, 10000);
  }
}

api.start().then(connect).catch(console.error);
