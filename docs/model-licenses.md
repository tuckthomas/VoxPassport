# VoxPassport Model License Inventory

> **Re-check every upstream license immediately before public release, redistribution, hosted commercial use, or bundling model weights.** Model licenses and upstream terms can change. “Open weights,” “open source,” “downloadable,” and “commercially redistributable” are different claims.

This document is a release-review aid, not legal advice and not the source of runtime behavior. The model registry/manifests contain the metadata exposed by VoxPassport; a release process must independently verify current upstream terms.

## Current policy

- Models with unclear or non-commercial-only terms must not be silently bundled as production defaults.
- `installable=true` means VoxPassport has a configured download path; it does **not** mean redistribution/commercial rights have been legally verified.
- Models requiring remote code execution must be clearly surfaced and require the intended trust approval.
- Attribution/notice obligations must be carried into the appropriate About/Credits/release materials.
- Model weights should not be bundled in an installer unless redistribution is explicitly permitted.
- Provider/API terms are separate from downloadable-model licenses and must be reviewed independently.
- A model manifest value such as `license: "verify upstream model terms"` is deliberately unresolved metadata, not permission to ship.

## Current/relevant model inventory

The table below combines the existing documented license snapshot with current manifest metadata. Rows marked **VERIFY** intentionally remain unresolved until a release-grade upstream review is performed.

| Model / family | Repository metadata / recorded terms | Commercial use | Redistribution | Release note |
| --- | --- | --- | --- | --- |
| NVIDIA Parakeet TDT 0.6B v3 | CC BY 4.0 recorded in prior benchmark/review metadata | Verify attribution/current upstream terms | Verify attribution/current upstream terms | Current reference ASR candidate; re-check upstream before release |
| NVIDIA Canary-1B-v2 | CC BY 4.0 recorded in prior review metadata | Verify current upstream terms | Verify current upstream terms | Candidate/research path |
| NVIDIA Nemotron 3.5 ASR Streaming 0.6B | OpenMDW-1.1 recorded in prior review metadata | **VERIFY** | **VERIFY** | Do not infer rights from NeMo code license |
| Xiaomi MiLMMT-46 1B / 4B | Apache-licensed code; checkpoint/base-model terms require separate verification | **VERIFY** | **VERIFY** | Review checkpoint/base-model terms, not only repository code |
| NVIDIA Riva Translate family | NVIDIA model terms recorded in prior review metadata | **VERIFY** | **VERIFY** | Review the exact checkpoint/service terms used |
| Silero VAD | MIT recorded in current project metadata | Verify current upstream | Verify current upstream | Lightweight VAD dependency |
| OmniVoice | Current manifest/catalog metadata requires upstream verification before distribution | **VERIFY** | **VERIFY** | Do not bundle merely because the runtime adapter exists |
| Higgs TTS 3 / native Q4 path | Current project metadata does not establish release-grade commercial/redistribution rights | **VERIFY** | **VERIFY** | Keep unresolved until exact model/code assets are reviewed |
| MOSS-TTS v1.5 | Manifest: `verify upstream model terms` | **VERIFY** | **VERIFY** | Current manifest is intentionally unresolved |
| VoxCPM 2 | Manifest: `verify upstream model terms` | **VERIFY** | **VERIFY** | Current manifest is intentionally unresolved |
| XTTS-v2 Romanian v2 | Manifest records Coqui Public Model License (CPML) | **VERIFY** | **VERIFY** | Verify CPML plus the Romanian fine-tune/checkpoint terms before release |
| Meta SeamlessM4T / SeamlessStreaming research paths | CC BY-NC 4.0 recorded in prior project review | Non-commercial under recorded snapshot; re-check current terms | Restricted under recorded snapshot | Must not be promoted to a commercial default based on old metadata |

## TTS manifest metadata currently represented in the repository

Current local TTS manifests include:

```text
omnivoice-stock
higgs-tts-3
higgs-tts-3-q4_k_m
moss-tts-1.5
voxcpm-2
xtts-v2-romanian-v2
```

The manifest registry fields are operational metadata used by the product catalog. Examples include:

```json
{
  "license": "verify upstream model terms",
  "commercial_use": "verify",
  "redistribution": "verify"
}
```

and, for the current XTTS Romanian manifest:

```json
{
  "license": "Coqui Public Model License (CPML)",
  "commercial_use": "verify",
  "redistribution": "verify"
}
```

Those values intentionally prevent the application architecture from pretending that adapter support equals shipping permission.

## Pre-release verification checklist

For every model actually included, recommended, hosted, or redistributed in a release:

- [ ] Record exact upstream repository/model ID and revision/commit.
- [ ] Capture the exact weight/checkpoint license and any separate code license.
- [ ] Check whether base-model or fine-tune terms also apply.
- [ ] Verify commercial-use rights for the intended deployment model.
- [ ] Verify redistribution/bundling rights.
- [ ] Verify attribution/notice requirements.
- [ ] Review acceptable-use/prohibited-use terms where applicable.
- [ ] Review `trust_remote_code` / third-party code-execution implications.
- [ ] Record whether hosted API/service terms differ from downloadable-weight terms.
- [ ] Update the corresponding registry/manifest metadata only after the upstream review is complete.

## Product/UI behavior

The canonical Expo Models & Engines surface should display license/trust metadata supplied by the backend catalog. It must not convert an unresolved `verify` value into a positive legal claim.

Likewise:

```text
installable
```

is an installation-action property, not a license conclusion.

A model may be:

- discoverable but not installable;
- installable but not implemented by a production runtime adapter;
- runnable locally but not redistributable;
- benchmarkable for research but unsuitable for a commercial release.

These states must remain distinct.

## References retained for release review

These are reference destinations from the prior project review and should be checked again at release time rather than treated as permanently authoritative:

- NVIDIA Open Model / OpenMDW terms
- Creative Commons CC BY 4.0
- Creative Commons CC BY-NC 4.0
- Apache License 2.0
- Gemma terms where relevant to a dependent checkpoint
- Coqui Public Model License for XTTS-family assets
- each model's exact Hugging Face/upstream repository license/README at the pinned revision

Do not rely on this document alone to approve distribution.
