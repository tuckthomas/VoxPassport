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

          const xttsId = 'xtts-v2-romanian-v2';
          if (typeof MODEL_DISPLAY_NAMES !== 'undefined') {
            MODEL_DISPLAY_NAMES[xttsId] = 'XTTS-v2 Romanian v2';
          }
          if (typeof MODEL_TAG_STATUS !== 'undefined') {
            MODEL_TAG_STATUS[xttsId] = 'Worker :8098';
          }
          if (typeof CANONICAL_MODEL_ALIASES !== 'undefined') {
            CANONICAL_MODEL_ALIASES[xttsId] = xttsId;
            CANONICAL_MODEL_ALIASES['eduardem-xtts-v2-romanian-v2'] = xttsId;
          }
          if (typeof MODEL_SPECS !== 'undefined') {
            MODEL_SPECS[xttsId] = { targetSeconds: 10, badge: '10S ENROLLMENT', tier: 'short' };
          }
          if (typeof TTS_MODEL_SPECS !== 'undefined' && !TTS_MODEL_SPECS.some(m => m.id === xttsId)) {
            TTS_MODEL_SPECS.push({
              id: xttsId,
              name: 'XTTS-v2 Romanian v2',
              shortName: 'XTTS Romanian v2',
              meta: '24kHz • ~2.35 GB checkpoint',
              vramGb: 3.5,
              desc: 'Streaming English/Romanian Voice Cloning',
              license: 'CPML',
              commercialUse: 'verify',
              upstreamId: 'eduardem/xtts-v2-romanian-v2',
              licenseUrl: 'https://huggingface.co/eduardem/xtts-v2-romanian-v2',
            });
          }

          if (typeof loadModelHub === 'function') {
            loadModelHub();
          } else {
            renderTtsModelWidgets();
            renderVadModelWidgets();
          }
        })();
      `);
    } catch (err) {
      console.warn('Could not extend engine catalog:', err);
    }
  });
})();
