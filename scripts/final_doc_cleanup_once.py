from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(rel: str, old: str, new: str, count: int = 1) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{rel}: expected {count}, found {actual}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "runtime/inference/server/main.py",
    'logger.info("VoxPassport UI/API ready at http://127.0.0.1:8766")',
    'logger.info("VoxPassport API ready at http://127.0.0.1:8766; canonical Expo client at http://127.0.0.1:8081")',
)
replace_exact(
    "docs/tts-plugin-architecture.md",
    "Model Settings marks the active runtime broken if either supervised layer fails.",
    "The canonical Expo Runtime/Diagnostics surface marks the active TTS runtime broken when either supervised layer fails.",
)
replace_exact(
    "docs/xtts-romanian-low-vram.md",
    "`run.bat` starts only the main VoxPassport daemon. It does not start a primary TTS host or an XTTS host.",
    "`run.bat` starts the integrated VoxPassport runtime plus the canonical Expo web client. It does not prestart a primary TTS host or an XTTS host.",
)
replace_exact(
    "docs/model-bakeoff.md",
    "current installed/active state comes from Model Settings / Model Registry.",
    "current installed/active state comes from the Expo Models & Engines surface / Model Registry.",
)

# Remove one-shot machinery from the committed result.
(ROOT / "scripts/final_doc_cleanup_once.py").unlink()
(ROOT / ".github/workflows/final-doc-cleanup-once.yml").unlink()
