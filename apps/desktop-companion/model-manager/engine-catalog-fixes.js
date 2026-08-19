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
          const ensureTts = (spec) => {
            if (!TTS_MODEL_SPECS.some(m => m.id === spec.id)) TTS_MODEL_SPECS.push(spec);
          };
          ensureTts({
            id: 'moss-tts-1.5',
            name: 'MOSS-TTS v1.5 (OpenMOSS)',
            shortName: 'MOSS-TTS v1.5',
            meta: '48kHz • local worker :8096',
            vramGb: 6.5,
            desc: 'Multilingual Local Transformer',
          });
          ensureTts({
            id: 'voxcpm-2',
            name: 'VoxCPM 2 (OpenBMB)',
            shortName: 'VoxCPM 2',
            meta: '48kHz • local worker :8097',
            vramGb: 4.8,
            desc: 'Multilingual Voice Cloning',
          });

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

          renderTtsModelWidgets();
          renderVadModelWidgets();
        })();
      `);
    } catch (err) {
      console.warn('Could not extend engine catalog:', err);
    }
  });
})();
