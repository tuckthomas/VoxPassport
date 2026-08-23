(() => {
  'use strict';
  const frame = document.getElementById('studioFrame');
  frame.addEventListener('load', () => {
    const w = frame.contentWindow;
    if (!w || w.__voxEngineCatalogRepairInstalled) return;
    w.__voxEngineCatalogRepairInstalled = true;
    try {
      w.eval(`
        (() => {
          const vad = VAD_MODEL_SPECS.find(m => m.id === 'silero-vad-v4')
            || VAD_MODEL_SPECS.find(m => m.id === 'silero-vad-v6.2.1');
          if (vad) {
            vad.id = 'silero-vad-v6.2.1';
            vad.name = 'Silero VAD v6.2.1';
            vad.shortName = 'Silero VAD v6.2.1';
            vad.meta = '32ms • pinned official v6.2.1';
            vad.vramGb = 0.05;
            vad.desc = 'Neural Voice Activity Detection';
          }
          if (typeof activeVadEngine !== 'undefined' && activeVadEngine === 'silero-vad-v4') {
            activeVadEngine = 'silero-vad-v6.2.1';
          }

          function estimatePluginVram(entry) {
            const tiers = entry?.expected_vram_tiers || {};
            const text = Object.values(tiers).join(' ');
            const match = text.match(/~?(\\d+(?:\\.\\d+)?)\\s*GB/i);
            return match ? Number(match[1]) : 0;
          }

          function pluginUiSpec(entry) {
            const id = entry.model_id;
            const downloadGb = Number(entry.estimated_download_size_gb || 0);
            return {
              id,
              name: entry.name || id,
              shortName: entry.name || id,
              meta: downloadGb > 0 ? ('Plugin • ' + downloadGb.toFixed(2) + ' GB download') : 'Manifest TTS plugin',
              vramGb: estimatePluginVram(entry),
              desc: entry.voice_cloning_support ? 'Streaming Voice Cloning Plugin' : 'Streaming TTS Plugin',
              license: entry.license || 'verify',
              commercialUse: entry.commercial_use || 'verify',
              upstreamId: entry.upstream_id || '',
            };
          }

          async function syncManifestTtsCatalog() {
            try {
              const response = await fetch(API_URL + '/models/available');
              if (!response.ok) return;
              const entries = await response.json();
              const plugins = Array.isArray(entries)
                ? entries.filter(entry => entry.capability === 'TTS' && entry.required_runtime === 'voxpassport.tts.v1')
                : [];

              for (const entry of plugins) {
                const id = entry.model_id;
                if (!id) continue;
                if (typeof MODEL_DISPLAY_NAMES !== 'undefined') {
                  MODEL_DISPLAY_NAMES[id] = entry.name || id;
                }
                if (typeof MODEL_TAG_STATUS !== 'undefined') {
                  MODEL_TAG_STATUS[id] = 'TTS Plugin';
                }
                if (typeof CANONICAL_MODEL_ALIASES !== 'undefined') {
                  CANONICAL_MODEL_ALIASES[id] = id;
                }
                if (typeof MODEL_SPECS !== 'undefined' && !MODEL_SPECS[id]) {
                  MODEL_SPECS[id] = { targetSeconds: 10, badge: '10S ENROLLMENT', tier: 'short' };
                }
                if (typeof TTS_MODEL_SPECS !== 'undefined') {
                  const runtimeSpec = pluginUiSpec(entry);
                  const existing = TTS_MODEL_SPECS.find(model => model.id === id);
                  if (existing) {
                    Object.assign(existing, runtimeSpec);
                  } else {
                    TTS_MODEL_SPECS.push(runtimeSpec);
                  }
                }
              }
              if (typeof renderTtsModelWidgets === 'function') renderTtsModelWidgets();
            } catch (err) {
              console.warn('Could not synchronize manifest TTS catalog:', err);
            }
          }

          if (typeof loadModelHub === 'function') {
            loadModelHub().finally(syncManifestTtsCatalog);
          } else {
            syncManifestTtsCatalog();
            renderVadModelWidgets();
          }
        })();
      `);
    } catch (err) {
      console.warn('Could not extend engine catalog:', err);
    }
  });
})();
