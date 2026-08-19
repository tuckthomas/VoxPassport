# Model Licenses — LiveTranslator

> **Re-check all licenses immediately before any public release or distribution.**
> Model licenses can change. "Open weights" ≠ "open source" ≠ "commercial use permitted."

## Candidate Model License Summary

| Model | Code License | Weight License | Commercial Use | Redistribution | Notes |
|-------|-------------|----------------|----------------|----------------|-------|
| NVIDIA Nemotron 3.5 ASR Streaming 0.6B | Apache-2.0 (NeMo) | OpenMDW-1.1 | Check OpenMDW-1.1 | Check OpenMDW-1.1 | Must verify per OpenMDW terms |
| NVIDIA Parakeet TDT 0.6B v3 | Apache-2.0 (NeMo) | CC BY 4.0 | Yes (with attribution) | Yes (with attribution) | Attribution required |
| NVIDIA Canary-1B-v2 | Apache-2.0 (NeMo) | CC BY 4.0 | Yes (with attribution) | Yes (with attribution) | Attribution required |
| Xiaomi MiLMMT-46-1B-v1.0 | Apache-2.0 | **CHECK: based on Gemma** | **Verify Gemma license** | **Verify** | Code is Apache-2.0 but checkpoint may inherit Gemma terms |
| Xiaomi MiLMMT-46-4B-v1.0 | Apache-2.0 | **CHECK: based on Gemma** | **Verify Gemma license** | **Verify** | Same as 1B |
| NVIDIA Riva-Translate-4B-Instruct-v2 | Apache-2.0 (NeMo) | NVIDIA Open Model License | Check NVIDIA terms | Check NVIDIA terms | Verify NVIDIA-specific commercial restrictions |
| k2-fsa OmniVoice | Apache-2.0 | **CHECK upstream** | **Verify at packaging** | **Verify** | Must verify distribution rights before release |
| Higgs TTS 3 | **UNKNOWN** | **UNKNOWN** | **NOT CONFIRMED** | **NOT CONFIRMED** | **Do not use as production default until verified** |
| Meta SeamlessM4T v2 | MIT (code) | CC BY-NC 4.0 | **No (non-commercial)** | **Restricted** | Research/non-commercial only — verify latest |
| Meta SeamlessStreaming | MIT (code) | CC BY-NC 4.0 | **No (non-commercial)** | **Restricted** | Same as above — verify latest |
| Silero VAD | MIT | MIT | Yes | Yes | Well-established, permissive |

## Verification Checklist (Pre-Release)

- [ ] NVIDIA Nemotron 3.5: Confirm OpenMDW-1.1 terms for target deployment scenario
- [ ] NVIDIA Parakeet TDT 0.6B v3: Confirm CC BY 4.0 attribution requirements
- [ ] NVIDIA Canary-1B-v2: Confirm CC BY 4.0 attribution requirements
- [ ] MiLMMT-46-1B: Determine if Gemma Prohibited Use Policy applies to weights
- [ ] MiLMMT-46-4B: Same as 1B
- [ ] Riva-Translate-4B: Confirm NVIDIA Open Model License scope
- [ ] OmniVoice: Confirm weight distribution rights before shipping an installer
- [ ] Higgs TTS 3: Do not ship until commercial rights are confirmed
- [ ] SeamlessM4T/Streaming: Confirm latest license — CC BY-NC 4.0 at time of writing

## Policy

- Models with unclear or non-commercial-only weights must not appear in default installation.
- Models that require remote code must have explicit user approval (see trust controls).
- Attribution requirements must be displayed in the application's About/Credits screen.
- No model weights are bundled in the installer unless redistribution is explicitly permitted.
- Default behavior is to download weights from the upstream source during setup.

## References

- OpenMDW-1.1: https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-nvidia-open-model-license/
- CC BY 4.0: https://creativecommons.org/licenses/by/4.0/
- CC BY-NC 4.0: https://creativecommons.org/licenses/by-nc/4.0/
- Apache-2.0: https://www.apache.org/licenses/LICENSE-2.0
- Gemma Terms: https://ai.google.dev/gemma/terms
- NVIDIA Open Model: https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/
