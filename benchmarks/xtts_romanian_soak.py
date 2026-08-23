"""Hardware soak test for alternating English/Romanian XTTS cloned turns.

The runtime-profile supervisor starts the correct dependency environment on an
ephemeral localhost port. The harness measures streaming latency and the active
XTTS driver's CUDA allocator over repeated turns.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import aiohttp

from runtime.inference.tts_plugins import TtsManifestCatalog, get_tts_runtime_supervisor
from runtime.workers.tts_host.drivers.xtts_common import target_conditioning_reference

MODEL_ID = "xtts-v2-romanian-v2"

RO_TEXTS = [
    "Bună ziua, mă bucur să vorbesc cu tine astăzi.",
    "Traducerea aceasta trebuie să sune natural și clar.",
    "Știu că vremea se schimbă repede în această perioadă.",
    "Putem continua conversația fără să așteptăm propoziții foarte lungi.",
]
EN_TEXTS = [
    "Hello, it is good to talk with you today.",
    "This translation should sound natural and clear.",
    "I know the weather changes quickly this time of year.",
    "We can keep talking without waiting for very long sentences.",
]


async def run_turn(session, endpoint: str, payload: dict) -> dict:
    started = time.perf_counter()
    first_byte = None
    total_bytes = 0
    async with session.post(endpoint + "/v1/audio/speech", json=payload) as response:
        if response.status != 200:
            detail = (await response.read()).decode("utf-8", errors="replace")[:1200]
            raise RuntimeError(f"TTS plugin host returned HTTP {response.status}: {detail}")
        async for chunk in response.content.iter_chunked(32768):
            if chunk and first_byte is None:
                first_byte = time.perf_counter()
            total_bytes += len(chunk)
    finished = time.perf_counter()
    async with session.get(endpoint + "/metrics") as metrics_response:
        metrics = await metrics_response.json(content_type=None)
    return {
        "ttfb_ms": round(((first_byte or finished) - started) * 1000, 1),
        "total_ms": round((finished - started) * 1000, 1),
        "audio_bytes": total_bytes,
        "memory": metrics,
    }


async def main_async(args) -> dict:
    project_root = Path(__file__).resolve().parents[1]
    profile_dir = Path(args.profiles_root or project_root / "data" / "voice_profiles") / args.profile_id
    canonical = profile_dir / "reference.wav"
    if not canonical.exists():
        raise FileNotFoundError(f"Missing canonical voice reference: {canonical}")

    catalog = TtsManifestCatalog().load()
    manifest = catalog.resolve(MODEL_ID)
    supervisor = get_tts_runtime_supervisor(manifest_catalog=catalog)
    endpoint, _caps = await supervisor.activate(manifest)

    timeout = aiohttp.ClientTimeout(total=300, sock_read=240)
    results = []
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for turn in range(args.turns):
                endpoint = await supervisor.ensure_active(manifest)
                language = "ro" if turn % 2 == 0 else "en"
                texts = RO_TEXTS if language == "ro" else EN_TEXTS
                target = target_conditioning_reference(profile_dir, language)
                payload = {
                    "model": MODEL_ID,
                    "input": texts[(turn // 2) % len(texts)],
                    "language": language,
                    "response_format": "pcm",
                    "ref_audio_path": str(canonical.resolve()),
                }
                if target is not None:
                    payload["target_conditioning_path"] = str(target.resolve())
                row = await run_turn(session, endpoint, payload)
                row.update({"turn": turn + 1, "language": language, "hybrid_conditioning": target is not None})
                results.append(row)
                print(
                    f"turn {turn + 1:02d}/{args.turns} {language} "
                    f"TTFB={row['ttfb_ms']:.0f}ms total={row['total_ms']:.0f}ms "
                    f"allocated={row['memory'].get('allocated_mb', '?')}MB "
                    f"reserved={row['memory'].get('reserved_mb', '?')}MB"
                )
    finally:
        await supervisor.release(manifest)

    allocated = [r["memory"].get("allocated_mb") for r in results if isinstance(r["memory"].get("allocated_mb"), (int, float))]
    reserved = [r["memory"].get("reserved_mb") for r in results if isinstance(r["memory"].get("reserved_mb"), (int, float))]
    report = {
        "profile_id": args.profile_id,
        "model_id": MODEL_ID,
        "runtime_profile": manifest.runtime_profile,
        "turns": args.turns,
        "created_at": datetime.now().isoformat(),
        "summary": {
            "median_ttfb_ms": round(statistics.median(r["ttfb_ms"] for r in results), 1),
            "median_total_ms": round(statistics.median(r["total_ms"] for r in results), 1),
            "allocated_growth_mb": round(allocated[-1] - allocated[0], 1) if len(allocated) > 1 else None,
            "reserved_growth_mb": round(reserved[-1] - reserved[0], 1) if len(reserved) > 1 else None,
            "peak_allocated_mb": max(allocated) if allocated else None,
            "peak_reserved_mb": max(reserved) if reserved else None,
        },
        "turn_results": results,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="XTTS Romanian alternating-turn VRAM soak test")
    parser.add_argument("profile_id")
    parser.add_argument("--profiles-root", default="")
    parser.add_argument("--turns", type=int, default=50)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    report = asyncio.run(main_async(args))
    if args.output:
        output = Path(args.output)
    else:
        output = Path(__file__).resolve().parent / "xtts_romanian" / "results" / f"soak-{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved soak report: {output}")


if __name__ == "__main__":
    main()
