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
