/**
 * LiveTranslator — Google Meet Content Script
 * Injects a clean subtitle container into the Google Meet DOM.
 */

(function () {
  if (document.getElementById("livetranslator-meet-overlay")) return;

  const container = document.createElement("div");
  container.id = "livetranslator-meet-overlay";
  container.innerHTML = `
    <div class="lt-subtitles-box">
      <div class="lt-caption-line lt-outbound">
        <span class="lt-badge lt-en">YOU</span>
        <span class="lt-text lt-ro-text" id="lt-outbound-text">Live translation ready...</span>
      </div>
      <div class="lt-caption-line lt-inbound">
        <span class="lt-badge lt-ro">THEM</span>
        <span class="lt-text lt-en-text" id="lt-inbound-text">Waiting for Romanian speech...</span>
      </div>
    </div>
  `;
  document.body.appendChild(container);

  const outboundText = document.getElementById("lt-outbound-text");
  const inboundText = document.getElementById("lt-inbound-text");

  // Listen for messages forwarded by background service worker
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "caption") {
      const isOutbound = (msg.language === "en" && msg.event_type.includes("source")) ||
                         (msg.language === "ro" && msg.event_type.includes("translation"));

      if (isOutbound && outboundText) {
        outboundText.textContent = msg.text;
      } else if (!isOutbound && inboundText) {
        inboundText.textContent = msg.text;
      }
    }
  });
})();
