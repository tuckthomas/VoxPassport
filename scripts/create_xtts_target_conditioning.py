"""Create an optional target-language XTTS conditioning reference with MOSS.

This is an offline enrollment utility. It never replaces ``reference.wav``.
The heavy teacher model may temporarily use most of the GPU; the generic TTS
host switches from XTTS to MOSS, creates the Romanian WAV, then unloads MOSS.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import aiohttp

MOSS_MODEL_ID = "moss-tts-1.5"

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

    if args.moss_url:
        raise ValueError(
            "--moss-url is no longer a client-side adapter setting. Set VOXPASSPORT_MOSS_TTS_URL before starting run.bat, or use the default MOSS backend on port 8096."
        )

    prompt = args.text.strip() or DEFAULT_ROMANIAN_PROMPT
    host = args.tts_host_url.rstrip("/")
    timeout = aiohttp.ClientTimeout(total=300, sock_read=240)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Loading MOSS automatically unloads whichever TTS plugin was resident,
        # including XTTS, so the teacher can temporarily use the GPU.
        load_result = await _post_json(session, host + "/load", {"model_id": MOSS_MODEL_ID})
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
        async with session.post(host + "/v1/audio/speech", json=payload) as response:
            audio = await response.read()
            if response.status != 200:
                detail = audio.decode("utf-8", errors="replace")[:1500]
                raise RuntimeError(f"MOSS teacher synthesis failed: {detail}")
        await _post_json(session, host + "/unload", {"model_id": MOSS_MODEL_ID})

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
                "tts_host": args.tts_host_url,
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
    parser.add_argument("--moss-url", default="", help=argparse.SUPPRESS)
    parser.add_argument("--text", default=DEFAULT_ROMANIAN_PROMPT)
    args = parser.parse_args()
    output = asyncio.run(create_conditioning(args))
    print(f"Created XTTS Romanian conditioning reference: {output}")
    print("Canonical reference.wav was left unchanged.")


if __name__ == "__main__":
    main()
