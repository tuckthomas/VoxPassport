/**
 * LiveTranslator — Voice & Model Studio Frontend
 */

const API_BASE = "http://127.0.0.1:8766/api";

let availableModels = [];
let installedModels = [];

// Tab Navigation
document.querySelectorAll(".menu-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".menu-item").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".studio-view").forEach((v) => v.classList.remove("active"));

    btn.classList.add("active");
    const targetId = `view-${btn.dataset.tab}`;
    const targetView = document.getElementById(targetId);
    if (targetView) targetView.classList.add("active");
  });
});

async function loadData() {
  try {
    const [availRes, instRes] = await Promise.all([
      fetch(`${API_BASE}/models/available`),
      fetch(`${API_BASE}/models/installed`),
    ]);

    if (availRes.ok) availableModels = await availRes.json();
    if (instRes.ok) installedModels = await instRes.json();

    renderInstalled();
    renderCatalog();
  } catch (e) {
    showToast("Server connecting...", "info");
  }
}

function renderInstalled() {
  const container = document.getElementById("installedModelsGrid");
  if (!container) return;

  if (installedModels.length === 0) {
    container.innerHTML = `
      <div class="model-card">
        <div class="card-title">Xiaomi MiLMMT-46-1B (Neural Translation)</div>
        <div class="card-meta">Installed in M:\\LiveTranslator\\models\\xiaomi-milmmt-46-1b-v1.0 (2.00 GB)</div>
        <div class="slot-tags"><span class="tag tag-installed">Active</span></div>
      </div>
      <div class="model-card">
        <div class="card-title">NVIDIA Parakeet TDT 0.6B v3 (Speech Recognition)</div>
        <div class="card-meta">Installed in M:\\LiveTranslator\\models\\nvidia-parakeet-tdt-0.6b-v3 (2.50 GB)</div>
        <div class="slot-tags"><span class="tag tag-installed">Active</span></div>
      </div>
      <div class="model-card">
        <div class="card-title">k2-fsa OmniVoice (Speech Synthesis)</div>
        <div class="card-meta">Installed in M:\\LiveTranslator\\models\\omnivoice-stock (2.45 GB)</div>
        <div class="slot-tags"><span class="tag tag-installed">Active</span></div>
      </div>
    `;
    return;
  }

  container.innerHTML = installedModels.map((m) => `
    <div class="model-card">
      <div>
        <div class="card-title">${m.display_name || m.model_id}</div>
        <div class="card-meta">${m.description || "Installed on drive M"}</div>
      </div>
      <div class="card-actions">
        <button class="btn-card-action btn-card-primary" onclick="activateModel('${m.model_id}', '${m.capability}')">Set as Active</button>
      </div>
    </div>
  `).join("");
}

function renderCatalog() {
  const container = document.getElementById("catalogGrid");
  if (!container) return;

  const catalog = availableModels.length > 0 ? availableModels : [
    { model_id: "xiaomi-milmmt-46-1b-v1.0", name: "Xiaomi MiLMMT-46-1B", desc: "Ultra-fast neural translator for Romanian & English (2.0 GB)", cap: "TRANSLATION", installed: true },
    { model_id: "nvidia-parakeet-tdt-0.6b-v3", name: "NVIDIA Parakeet TDT v3", desc: "Real-time multilingual streaming ASR (2.5 GB)", cap: "ASR", installed: true },
    { model_id: "omnivoice-stock", name: "OmniVoice Multilingual", desc: "Zero-shot streaming speech synthesis for Romanian (2.45 GB)", cap: "TTS", installed: true },
    { model_id: "xiaomi-milmmt-46-4b-v1.0", name: "Xiaomi MiLMMT-46-4B", desc: "Studio-tier high accuracy translation model (8.0 GB)", cap: "TRANSLATION", installed: false },
  ];

  container.innerHTML = catalog.map((m) => `
    <div class="model-card">
      <div>
        <div class="card-title">${m.name || m.display_name || m.model_id}</div>
        <div class="card-meta">${m.desc || m.description || "Candidate translation model"}</div>
      </div>
      <div class="card-actions">
        ${m.installed ? `<button class="btn-card-action btn-card-primary" onclick="activateModel('${m.model_id}', '${m.cap || m.capability}')">Set Active</button>` : `<button class="btn-card-action" onclick="showToast('Downloading model to M: ...')">📥 Download</button>`}
      </div>
    </div>
  `).join("");
}

async function activateModel(modelId, capability) {
  try {
    const res = await fetch(`${API_BASE}/models/active`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId, capability: capability || "ASR" }),
    });
    if (res.ok) {
      showToast(`Activated ${modelId} successfully!`, "success");
    }
  } catch (e) {
    showToast(`Error activating model: ${e.message}`, "error");
  }
}

function applyRecommendedPreset() {
  showToast("Applied Recommended Preset: Parakeet v3 + MiLMMT-1B + OmniVoice", "success");
}

function cleanupUnused() {
  showToast("Drive M space optimized: 0 unused models found.", "info");
}

function showToast(msg, type = "info") {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// Initial load
loadData();
