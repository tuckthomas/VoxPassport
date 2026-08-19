/**
 * LiveTranslator — Desktop Overlay Frontend
 * Connects to ws://127.0.0.1:8765/ws/captions & http://127.0.0.1:8766/api/
 */

const WS_URL = "ws://127.0.0.1:8765/ws/captions";
const API_URL = "http://127.0.0.1:8766/api";

let ws = null;
let currentTtsMode = "stock";

// DOM Elements
const outboundSource = document.getElementById("outboundSource");
const outboundTranslated = document.getElementById("outboundTranslated");
const inboundSource = document.getElementById("inboundSource");
const inboundTranslated = document.getElementById("inboundTranslated");
const statusPill = document.getElementById("statusPill");
const statusText = document.getElementById("statusText");
const voiceLabel = document.getElementById("voiceLabel");
const btnModeTwoWay = document.getElementById("btnModeTwoWay");
const btnModeCaptionsOnly = document.getElementById("btnModeCaptionsOnly");

function connectWebSocket() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    statusPill.className = "status-indicator online";
    statusText.textContent = "Translating Live";
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleCaptionEvent(data);
    } catch (e) {
      console.error("Failed to parse event:", e);
    }
  };

  ws.onclose = () => {
    statusPill.className = "status-indicator offline";
    statusText.textContent = "Connecting...";
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = () => {
    ws.close();
  };
}

function handleCaptionEvent(event) {
  if (event.type === "caption") {
    const isOutbound = event.language === "ro" || event.utterance_id?.startsWith("out-");
    
    if (isOutbound) {
      if (event.event_type === "SOURCE_TRANSCRIPT") {
        outboundSource.textContent = event.text;
      } else if (event.event_type === "TRANSLATED_FINAL" || event.event_type === "TRANSLATED_PARTIAL") {
        outboundTranslated.textContent = event.text;
      }
    } else {
      if (event.event_type === "SOURCE_TRANSCRIPT") {
        inboundSource.textContent = event.text;
      } else if (event.event_type === "TRANSLATED_FINAL" || event.event_type === "TRANSLATED_PARTIAL") {
        inboundTranslated.textContent = event.text;
      }
    }
  }
}

async function setMode(modeName) {
  try {
    const res = await fetch(`${API_URL}/mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: modeName }),
    });
    if (res.ok) {
      if (modeName === "full_duplex") {
        btnModeTwoWay.classList.add("active");
        btnModeCaptionsOnly.classList.remove("active");
      } else {
        btnModeCaptionsOnly.classList.add("active");
        btnModeTwoWay.classList.remove("active");
      }
    }
  } catch (e) {
    console.error("Failed to switch mode:", e);
  }
}

async function toggleVoice() {
  currentTtsMode = currentTtsMode === "stock" ? "cloned" : "stock";
  voiceLabel.textContent = currentTtsMode === "stock" ? "Natural Romanian Voice" : "Cloned Voice Profile";
  
  try {
    await fetch(`${API_URL}/tts-mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tts_mode: currentTtsMode === "stock" ? "stock" : "cloned" }),
    });
  } catch (e) {
    console.error("Failed to toggle voice:", e);
  }
}

function clearCaptions() {
  outboundSource.textContent = "Listening for speech...";
  outboundTranslated.textContent = "Traducerea în limba română va apărea instantaneu aici...";
  inboundSource.textContent = "Așteptare vorbire din conferință...";
  inboundTranslated.textContent = "English translation of the meeting will appear here...";
}

// Initial start
connectWebSocket();
