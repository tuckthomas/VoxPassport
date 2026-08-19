/**
 * LiveTranslator — Manifest V3 Extension Service Worker
 * Bridges local daemon WebSocket (ws://127.0.0.1:8765/ws/captions) to Google Meet content scripts.
 */

let ws = null;
let activeTabId = null;

function connectToLocalDaemon() {
  try {
    ws = new WebSocket("ws://127.0.0.1:8765/ws/captions");

    ws.onopen = () => {
      console.log("[LiveTranslator Extension] Connected to local translation daemon.");
      chrome.storage.local.set({ daemonConnected: true });
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        // Forward caption / telemetry to all open Google Meet tabs
        chrome.tabs.query({ url: "https://meet.google.com/*" }, (tabs) => {
          for (const tab of tabs) {
            chrome.tabs.sendMessage(tab.id, data).catch(() => {});
          }
        });
      } catch (e) {
        console.error("Parse error:", e);
      }
    };

    ws.onclose = () => {
      console.warn("[LiveTranslator Extension] Daemon disconnected. Reconnecting in 3s...");
      chrome.storage.local.set({ daemonConnected: false });
      setTimeout(connectToLocalDaemon, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  } catch (e) {
    setTimeout(connectToLocalDaemon, 3000);
  }
}

// Start connection
connectToLocalDaemon();
