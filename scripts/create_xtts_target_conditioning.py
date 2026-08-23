"""Create an optional target-language XTTS conditioning reference with MOSS.

This is an offline enrollment utility.  It never replaces ``reference.wav``.
The heavy teacher model may temporarily use most of the GPU; XTTS is asked to
unload first, then the resulting Romanian WAV is saved under
``conditioning/ro.wav`` for later lightweight XTTS inference.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import aiohttp

from runtime.inference.adapters.tts.moss_tts_adapter import MossTtsAdapter

DEFAULT_ROMANIAN_PROMPT = (
    "Ștefan și Ioana călătoresc prin România, vorbind clar despre țară, familie, "
    "muzică, vreme și lucrurile frumoase pe care le întâlnesc în fiecare zi."
)


async def _unload_xtts(endpoint: str) -> None:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(endpoint.rstrip("/") + "/unload", json={}) as response:
                await response.read()
    except Exception:
        # The worker may not be running yet; teacher generation can still proceed.
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

    await _unload_xtts(args.xtts_url)
    teacher = MossTtsAdapter(endpoint_url=args.moss_url, profiles_root=profiles_root)
    await teacher.load()
    if not await teacher.health_check():
        raise RuntimeError(
            f"MOSS teacher worker is not reachable at {args.moss_url}. Start the MOSS worker before running this utility."
        )

    prompt = args.text.strip() or DEFAULT_ROMANIAN_PROMPT
    audio = await teacher.generate_cloned_audio(
        text=prompt,
        ref_audio_path=str(reference),
        ref_text=reference_text,
        language="Romanian",
    )
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
                "teacher_endpoint": args.moss_url,
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
    parser.add_argument("--moss-url", default="http://127.0.0.1:8096")
    parser.add_argument("--xtts-url", default="http://127.0.0.1:8098")
    parser.add_argument("--text", default=DEFAULT_ROMANIAN_PROMPT)
    args = parser.parse_args()
    output = asyncio.run(create_conditioning(args))
    print(f"Created XTTS Romanian conditioning reference: {output}")
    print("Canonical reference.wav was left unchanged.")


if __name__ == "__main__":
    main()
