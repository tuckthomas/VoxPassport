"""Create an optional target-language XTTS conditioning reference with MOSS.

This is an offline enrollment utility. It never replaces ``reference.wav``.
The XTTS-capable host is unloaded first so the heavier MOSS teacher can use the
GPU, then the generated Romanian WAV is saved for later XTTS conditioning.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import aiohttp

MOSS_MODEL_ID = "moss-tts-1.5"
XTTS_MODEL_ID = "xtts-v2-romanian-v2"

DEFAULT_ROMANIAN_PROMPT = (
    "Ștefan și Ioana călătoresc prin România, vorbind clar despre țară, familie, "
    "muzică, vreme și lucrurile frumoase pe care le întâlnesc în fiecare zi."
)


async def _post_json(session, url: str, payload: dict) -> dict:
    async with session.post(url, json=payload) as response:
        body = await response.json(content_type=None)
        if response.status != 200:
            raise RuntimeError(body.get("error") or f"TTS plugin host returned HTTP {response.status}")
        return body


async def _best_effort_unload(session, host: str, model_id: str) -> None:
    try:
        await _post_json(session, host.rstrip("/") + "/unload", {"model_id": model_id})
    except Exception:
        # The corresponding host may not be running or the model may not be
        # resident. Teacher generation can still proceed if the GPU is free.
        pass


async def create_conditioning(args) -> Path:
    project_root = Path(__file__).resolve().parents[1]
    profiles_root = Path(args.profiles_root or project_root / "data" / "voice_profiles")
    profile_dir = profiles_root / args.profile_id
    reference = profile_dir / "reference.wav"
    transcript_path = profile_dir / "reference.txt"
    if not reference.exists():
        raise FileNotFoundError(f"Voice profile has no canonical reference.wav: {reference}")
    if not transcript_path.exists():
        raise FileNotFoundError(
            "MOSS cross-lingual teacher generation requires the canonical reference transcript"
        )
    reference_text = transcript_path.read_text(encoding="utf-8").strip()
    if not reference_text:
        raise ValueError("The canonical reference transcript is empty")

    prompt = args.text.strip() or DEFAULT_ROMANIAN_PROMPT
    primary_host = args.tts_host_url.rstrip("/")
    xtts_host = args.xtts_host_url.rstrip("/")
    timeout = aiohttp.ClientTimeout(total=300, sock_read=240)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # XTTS runs in an isolated environment on a separate generic protocol
        # host. Explicitly evict it before temporarily loading the MOSS teacher.
        await _best_effort_unload(session, xtts_host, XTTS_MODEL_ID)

        load_result = await _post_json(session, primary_host + "/load", {"model_id": MOSS_MODEL_ID})
        if not load_result.get("success"):
            raise RuntimeError(load_result.get("error") or "Could not load MOSS teacher plugin")

        payload = {
            "model": MOSS_MODEL_ID,
            "input": prompt,
            "language": "ro",
            "response_format": "wav",
            "ref_audio_path": str(reference.resolve()),
            "ref_text": reference_text,
        }
        try:
            async with session.post(primary_host + "/v1/audio/speech", json=payload) as response:
                audio = await response.read()
                if response.status != 200:
                    detail = audio.decode("utf-8", errors="replace")[:1500]
                    raise RuntimeError(f"MOSS teacher synthesis failed: {detail}")
        finally:
            await _best_effort_unload(session, primary_host, MOSS_MODEL_ID)

    if len(audio) <= 500:
        raise RuntimeError("MOSS teacher returned no usable conditioning audio")

    conditioning_dir = profile_dir / "conditioning"
    conditioning_dir.mkdir(parents=True, exist_ok=True)
    wav_path = conditioning_dir / "ro.wav"
    wav_path.write_bytes(audio)
    (conditioning_dir / "ro.txt").write_text(prompt, encoding="utf-8")
    (conditioning_dir / "ro.json").write_text(
        json.dumps(
            {
                "language": "ro",
                "purpose": "XTTS target-language GPT conditioning only",
                "canonical_identity_reference": "../reference.wav",
                "teacher": "MOSS-TTS v1.5",
                "teacher_protocol": "voxpassport.tts.v1",
                "teacher_host": primary_host,
                "xtts_host": xtts_host,
                "created_unix": time.time(),
                "text": prompt,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return wav_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Romanian target-language conditioning for an existing voice profile"
    )
    parser.add_argument("profile_id", help="Existing VoxPassport voice profile directory name")
    parser.add_argument("--profiles-root", default="")
    parser.add_argument("--tts-host-url", default="http://127.0.0.1:8098")
    parser.add_argument("--xtts-host-url", default="http://127.0.0.1:8099")
    parser.add_argument("--text", default=DEFAULT_ROMANIAN_PROMPT)
    args = parser.parse_args()
    output = asyncio.run(create_conditioning(args))
    print(f"Created XTTS Romanian conditioning reference: {output}")
    print("Canonical reference.wav was left unchanged.")


if __name__ == "__main__":
    main()
