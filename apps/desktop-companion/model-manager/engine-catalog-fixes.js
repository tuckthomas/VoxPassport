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
          const ensure = (spec) => {
            if (!TTS_MODEL_SPECS.some(m => m.id === spec.id)) TTS_MODEL_SPECS.push(spec);
          };
          ensure({
            id: 'moss-tts-1.5',
            name: 'MOSS-TTS v1.5 (OpenMOSS)',
            shortName: 'MOSS-TTS v1.5',
            meta: '48kHz • local worker :8096',
            vramGb: 6.5,
            desc: 'Multilingual Local Transformer',
          });
          ensure({
            id: 'voxcpm-2',
            name: 'VoxCPM 2 (OpenBMB)',
            shortName: 'VoxCPM 2',
            meta: '48kHz • local worker :8097',
            vramGb: 4.8,
            desc: 'Multilingual Voice Cloning',
          });
          renderTtsModelWidgets();
        })();
      `);
    } catch (err) {
      console.warn('Could not extend TTS engine catalog:', err);
    }
  });
})();
