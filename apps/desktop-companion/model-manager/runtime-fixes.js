(() => {
  'use strict';

  const frame = document.getElementById('studioFrame');
  let liveWs = null;
  let liveActive = false;
  let lastStatus = null;

  const api = async (w, path, options = {}) => {
    const res = await w.fetch(path, options);
    let data = {};
    try { data = await res.clone().json(); } catch (_) {}
    if (!res.ok || data.success === false) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
  };

  const lexical = (w, expression, fallback = null) => {
    try { return w.eval(expression); } catch (_) { return fallback; }
  };

  const setLexical = (w, name, value) => {
    try { w.eval(`${name} = ${JSON.stringify(value)}`); } catch (_) {}
  };

  function activeTts(w) {
    const value = lexical(w, 'activeSystemTtsEngine', null);
    return value || lastStatus?.active_slots?.TTS || 'omnivoice';
  }

  function targetLanguage(w) {
    return w.document.getElementById('liveTargetLangSelect')?.value
      || w.document.getElementById('targetLangSelect')?.value
      || w.document.getElementById('studioSampleOutputLangSelect')?.value
      || 'ro';
  }

  function voiceStudioVisible(w) {
    const view = w.document.getElementById('viewVoiceStudio');
    return !!view && view.style.display !== 'none';
  }

  function installCompatibilityTimerSentinel(w) {
    // The redesigned studio intentionally removed model binding from profiles,
    // but the old recorder still reads this legacy element to choose duration.
    // Keep it only as a 15-second timer sentinel; fetch interception below sends
    // the actual active TTS engine for preview generation.
    if (!w.document.getElementById('studioCloneModelSelect')) {
      const input = w.document.createElement('input');
      input.type = 'hidden';
      input.id = 'studioCloneModelSelect';
      input.value = 'higgs-tts-3';
      w.document.body.appendChild(input);
    }
  }

  function normalizeRecordingLabels(w) {
    const walk = w.document.createTreeWalker(w.document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walk.nextNode())) {
      if (node.nodeValue && node.nodeValue.includes('10s Recording')) {
        node.nodeValue = node.nodeValue.replaceAll('10s Recording', '15s Recording');
      }
      if (node.nodeValue && node.nodeValue.includes('10S ENROLLMENT')) {
        node.nodeValue = node.nodeValue.replaceAll('10S ENROLLMENT', '15S ENROLLMENT');
      }
    }
    const timer = w.document.getElementById('studioRecordTimer');
    if (timer && /^00:00\s*\/\s*00:/.test(timer.textContent || '')) {
      timer.textContent = '00:00 / 00:15';
    }
  }

  function patchFetch(w) {
    const originalFetch = w.fetch.bind(w);
    w.__voxOriginalFetch = originalFetch;

    w.fetch = async function(input, init = {}) {
      const raw = typeof input === 'string' ? input : (input?.url || '');
      const url = new URL(raw, w.location.href);
      const path = url.pathname;
      const next = { ...init };

      if ((path.endsWith('/api/voice/stage') || path.endsWith('/api/voice/enroll')) && next.body instanceof w.FormData) {
        const form = next.body;
        if (path.endsWith('/api/voice/stage')) {
          form.set('clone_model', activeTts(w));
          const refLang = w.document.getElementById('studioRefLangSelect')?.value || 'en';
          form.set('ref_lang', refLang);
        }
        if (!String(form.get('transcript') || '').trim() && voiceStudioVisible(w)) {
          const prompt = (w.document.getElementById('studioPromptBoxText')?.textContent || '')
            .trim().replace(/^"|"$/g, '');
          if (prompt) form.set('transcript', prompt);
        }
      }

      if (path.endsWith('/api/synthesize') && typeof next.body === 'string') {
        try {
          const body = JSON.parse(next.body);
          if (!body.target) body.target = targetLanguage(w);
          next.body = JSON.stringify(body);
        } catch (_) {}
      }

      const response = await originalFetch(input, next);
      if (path.endsWith('/api/voice/enroll') && !response.ok) {
        try {
          const detail = await response.clone().json();
          if (detail.error) w.showToast?.(detail.error);
        } catch (_) {}
      }
      return response;
    };
  }

  async function syncModelState(w) {
    try {
      const res = await w.__voxOriginalFetch('/api/status');
      if (!res.ok) return;
      lastStatus = await res.json();
      const slots = lastStatus.active_slots || {};
      if (slots.TTS) setLexical(w, 'activeSystemTtsEngine', slots.TTS);
      if (slots.ASR) setLexical(w, 'activeAsrEngine', slots.ASR);
      if (slots.NMT || slots.TRANSLATION) setLexical(w, 'activeNmtEngine', slots.NMT || slots.TRANSLATION);
      if (slots.VAD) setLexical(w, 'activeVadEngine', slots.VAD);
      w.renderTtsModelWidgets?.();
      w.renderAsrModelWidgets?.();
      w.renderNmtModelWidgets?.();
      w.renderVadModelWidgets?.();
    } catch (err) {
      console.warn('VoxPassport state sync failed:', err);
    }
  }

  async function activate(w, capability, modelId, stateVar, renderFn, label) {
    try {
      const data = await api(w, '/api/models/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ capability, model_id: modelId }),
      });
      const uiId = data.ui_model_id || modelId;
      if (stateVar) setLexical(w, stateVar, uiId);
      w[renderFn]?.();
      await syncModelState(w);
      w.showToast?.(`Active ${capability} model set to: ${label || uiId}`);
      return true;
    } catch (err) {
      w.showToast?.(`Could not activate ${label || modelId}: ${err.message}`);
      return false;
    }
  }

  function patchModelManager(w) {
    const originalSelectTts = w.selectActiveTtsEngine?.bind(w);

    w.toggleActiveTtsEngine = async (modelKey, label) => {
      const current = activeTts(w);
      if (current === modelKey) {
        w.showToast?.(`${label || modelKey} is already active. Select another engine to switch.`);
        w.renderTtsModelWidgets?.();
        return;
      }
      if (originalSelectTts) {
        await originalSelectTts(modelKey, label, true, true);
        await syncModelState(w);
      } else {
        await activate(w, 'TTS', modelKey, 'activeSystemTtsEngine', 'renderTtsModelWidgets', label);
      }
    };

    w.selectActiveAsrEngine = async (id, name) =>
      activate(w, 'ASR', id, 'activeAsrEngine', 'renderAsrModelWidgets', name);

    w.selectActiveNmtEngine = async (id, name) =>
      activate(w, 'NMT', id, 'activeNmtEngine', 'renderNmtModelWidgets', name);

    w.selectActiveVadEngine = async (id, name) =>
      activate(w, 'VAD', id, 'activeVadEngine', 'renderVadModelWidgets', name);

    w.installHfModel = async (modelId, upstreamId) => {
      try {
        const data = await api(w, '/api/models/install', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_id: modelId, upstream_id: upstreamId, revision: 'main' }),
        });
        w.showToast?.(`Download queued: ${upstreamId || modelId}`);
        setTimeout(() => w.loadHfCatalog?.(), 1000);
        return data;
      } catch (err) {
        w.showToast?.(`Download failed: ${err.message}`);
      }
    };

    const originalLoadHf = w.loadHfCatalog?.bind(w);
    w.loadModelHub = async () => {
      await w.checkHardwareProfile?.();
      await syncModelState(w);
      if (originalLoadHf) await originalLoadHf();
    };
  }

  function appendLine(el, text) {
    if (!el || !text) return;
    if (el.style.fontStyle === 'italic') {
      el.innerHTML = '';
      el.style.fontStyle = 'normal';
      el.style.color = 'var(--text-heading)';
    }
    const line = el.ownerDocument.createElement('div');
    line.style.marginBottom = '6px';
    line.textContent = text;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
  }

  async function configureLiveLanguage(w) {
    const remote = w.document.getElementById('liveTargetLangSelect')?.value || 'ro';
    try {
      await api(w, '/api/languages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_language: 'en', remote_language: remote }),
      });
      lastStatus = null;
    } catch (err) {
      w.showToast?.(`Could not switch live language: ${err.message}`);
    }
  }

  function patchLiveRuntime(w) {
    const originalLangChange = w.handleLiveTargetLangChange?.bind(w);
    w.handleLiveTargetLangChange = function() {
      originalLangChange?.();
      if (liveActive) configureLiveLanguage(w);
    };

    w.initLiveContinuousRecognition = () => {};
    w.processLivePhrasePipeline = async () => {};

    w.startLiveStreamMic = async () => {
      if (liveActive) return;
      await configureLiveLanguage(w);
      try {
        const profiles = await api(w, '/api/voice/profiles');
        const cloned = !!profiles.active_id;
        await api(w, '/api/tts-mode', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tts_mode: cloned ? 'tts_cloned' : 'tts_no_clone' }),
        });
      } catch (_) {}

      liveActive = true;
      setLexical(w, 'isLiveStreamingMic', true);
      const btn = w.document.getElementById('btnLiveStreamMic');
      const label = w.document.getElementById('liveStreamMicLabel');
      const status = w.document.getElementById('liveSourceStatusText');
      btn?.classList.add('recording');
      if (label) label.textContent = 'Stop Stream';
      if (status) status.textContent = 'Local ASR Streaming • Full Duplex Runtime';

      if (liveWs) try { liveWs.close(); } catch (_) {}
      liveWs = new w.WebSocket('ws://127.0.0.1:8765/ws/captions');
      liveWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type !== 'caption') return;
          const userLang = lastStatus?.user_language || 'en';
          const remoteLang = w.document.getElementById('liveTargetLangSelect')?.value || 'ro';
          if ((data.event_type === 'source_final' || data.event_type === 'source_partial') && data.language === userLang) {
            const interim = w.document.getElementById('liveInterimSpan');
            if (data.event_type === 'source_partial' && interim) {
              interim.textContent = data.text ? ` ${data.text}` : '';
            } else if (data.event_type === 'source_final') {
              if (interim) interim.textContent = '';
              appendLine(w.document.getElementById('liveCommittedTranscripts') || w.document.getElementById('liveSourceTranscript'), data.text);
              w.updateLiveWordCount?.();
            }
          }
          if (data.event_type === 'translation_final' && data.language === remoteLang) {
            appendLine(w.document.getElementById('liveTargetCaptionsText'), data.text);
            const latency = w.document.getElementById('liveLatencyMetrics');
            if (latency) latency.textContent = 'Local streaming';
          }
        } catch (err) {
          console.warn('Caption event parse failed:', err);
        }
      };
      liveWs.onerror = () => w.showToast?.('Could not connect to the local caption stream.');
    };

    w.stopLiveStreamMic = () => {
      liveActive = false;
      setLexical(w, 'isLiveStreamingMic', false);
      if (liveWs) {
        try { liveWs.close(); } catch (_) {}
        liveWs = null;
      }
      const btn = w.document.getElementById('btnLiveStreamMic');
      const label = w.document.getElementById('liveStreamMicLabel');
      const status = w.document.getElementById('liveSourceStatusText');
      btn?.classList.remove('recording');
      if (label) label.textContent = 'Live Record';
      if (status) status.textContent = 'Mic Inactive • Ready';
    };
  }

  function patchSidebarUpload(w) {
    w.submitSidebarUpload = async () => {
      const file = lexical(w, 'selectedSidebarFile', null);
      if (!file) return;
      const name = w.document.getElementById('profileNameInput')?.value.trim() || 'Uploaded Voice';
      const transcript = w.prompt(
        'Paste the exact transcript of this reference recording. A transcript is required so the voice profile remains portable across TTS engines.'
      );
      if (!transcript?.trim()) {
        w.showToast?.('Upload cancelled: an exact transcript is required for a universal voice profile.');
        return;
      }
      const form = new w.FormData();
      form.append('name', name);
      form.append('audio', file, file.name);
      form.append('transcript', transcript.trim());
      try {
        const data = await api(w, '/api/voice/enroll', { method: 'POST', body: form });
        w.showToast?.(`Enrolled '${data.profile_name}'`);
        setLexical(w, 'selectedSidebarFile', null);
        const input = w.document.getElementById('profileNameInput');
        if (input) input.value = '';
        const submit = w.document.getElementById('btnSidebarUploadSubmit');
        if (submit) submit.style.display = 'none';
        const label = w.document.getElementById('uploadSidebarLabel');
        if (label) label.textContent = 'Select WAV, MP3, M4A';
        await w.loadProfiles?.();
      } catch (err) {
        w.showToast?.(`Voice upload failed: ${err.message}`);
      }
    };
  }

  function installMutationRepair(w) {
    let queued = false;
    const observer = new w.MutationObserver(() => {
      if (queued) return;
      queued = true;
      w.requestAnimationFrame(() => {
        queued = false;
        installCompatibilityTimerSentinel(w);
        normalizeRecordingLabels(w);
      });
    });
    observer.observe(w.document.body, { childList: true, subtree: true, characterData: true });
  }

  frame.addEventListener('load', async () => {
    const w = frame.contentWindow;
    if (!w || w.__voxRuntimeRepairInstalled) return;
    w.__voxRuntimeRepairInstalled = true;

    patchFetch(w);
    installCompatibilityTimerSentinel(w);
    normalizeRecordingLabels(w);
    patchModelManager(w);
    patchLiveRuntime(w);
    patchSidebarUpload(w);
    installMutationRepair(w);
    await syncModelState(w);
    try { await w.loadProfiles?.(); } catch (_) {}
  });
})();
