(() => {
  'use strict';
  const frame = document.getElementById('studioFrame');
  frame.addEventListener('load', () => {
    const w = frame.contentWindow;
    if (!w || w.__voxStackUpgradeFixesInstalled) return;
    w.__voxStackUpgradeFixesInstalled = true;

    const originalInstall = w.installHfModel?.bind(w);
    w.installHfModel = async (modelId, upstreamId) => {
      const id = String(modelId || '').toLowerCase();
      const upstream = String(upstreamId || '').trim();

      if (id === 'silero-vad-v6.2.1' || id === 'silero-vad-v4' || id === 'snakers4-silero-vad') {
        w.showToast?.('Silero VAD v6.2.1 is runtime-managed and pinned to the official v6.2.1 release; no Hugging Face download is required.');
        return;
      }
      if (id === 'meta-omniasr-ctc-1b-v2') {
        w.showToast?.('OmniASR CTC 1B v2 is on the watchlist. Meta publishes it through the official omnilingual-asr package, but no Meta-owned v2 Hugging Face repo is configured yet.');
        return;
      }
      if (id === 'meta-omnilingual-mt') {
        w.showToast?.('Meta Omnilingual MT is watchlist-only until official downloadable model weights are published and verified.');
        return;
      }
      if (!upstream) {
        w.showToast?.('This catalog entry has no verified official Hugging Face repository yet.');
        return;
      }
      if (originalInstall) return originalInstall(modelId, upstreamId);
    };
  });
})();
