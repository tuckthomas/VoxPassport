"""Provision, inspect, and repair dependency-compatible TTS runtime profiles."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_FILE = PROJECT_ROOT / "runtime" / "profiles" / "runtime_profiles.json"


def _load_profiles() -> dict:
    data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    if int(data.get("schema_version", 0)) != 1:
        raise RuntimeError("Unsupported runtime profile schema")
    return dict(data.get("profiles") or {})


def _profile(profile_id: str) -> dict:
    profiles = _load_profiles()
    try:
        return dict(profiles[profile_id])
    except KeyError as exc:
        raise SystemExit(f"Unknown runtime profile: {profile_id}") from exc


def _interpreter_path(profile: dict) -> Path:
    env_name = str(profile.get("interpreter_env", "")).strip()
    override = os.getenv(env_name, "").strip() if env_name else ""
    raw = override or str(profile.get("interpreter", "")).strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _base_python(version: str) -> list[str]:
    project_python = PROJECT_ROOT / ".python312" / "python.exe"
    if project_python.exists():
        return [str(project_python)]
    if os.name == "nt" and shutil.which("py"):
        return ["py", f"-{version}"]
    return [sys.executable]


def _run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=str(PROJECT_ROOT), check=True)


def status(profile_id: str) -> int:
    profile = _profile(profile_id)
    interpreter = _interpreter_path(profile)
    provisioning = dict(profile.get("provisioning") or {})
    result = {
        "profile_id": profile_id,
        "installed": interpreter.exists(),
        "interpreter": str(interpreter),
        "strategy": provisioning.get("strategy", "unknown"),
        "prefer_uv": bool(provisioning.get("prefer_uv", False)),
    }
    print(json.dumps(result, indent=2))
    return 0 if interpreter.exists() else 1


def install(profile_id: str, *, repair: bool = False) -> int:
    profile = _profile(profile_id)
    provisioning = dict(profile.get("provisioning") or {})
    strategy = str(provisioning.get("strategy", "")).strip()
    interpreter = _interpreter_path(profile)

    if strategy == "shared-primary-environment":
        if interpreter.exists():
            print(f"Runtime profile {profile_id!r} uses the existing primary environment: {interpreter}")
            return 0
        raise SystemExit(
            f"Runtime profile {profile_id!r} requires the primary VoxPassport environment. Run install.bat first."
        )

    if strategy != "isolated-environment":
        raise SystemExit(f"Runtime profile {profile_id!r} has unsupported provisioning strategy {strategy!r}")

    venv_raw = str(provisioning.get("venv_dir", "")).strip()
    if not venv_raw:
        raise SystemExit(f"Runtime profile {profile_id!r} does not declare provisioning.venv_dir")
    venv_dir = Path(venv_raw)
    if not venv_dir.is_absolute():
        venv_dir = PROJECT_ROOT / venv_dir
    venv_dir = venv_dir.resolve()

    if repair and venv_dir.exists():
        print(f"Removing runtime profile environment for repair: {venv_dir}")
        shutil.rmtree(venv_dir)

    python_version = str(provisioning.get("python_version", "3.12"))
    prefer_uv = bool(provisioning.get("prefer_uv", False))
    uv = shutil.which("uv") if prefer_uv else None

    if not _venv_python(venv_dir).exists():
        if uv:
            _run([uv, "venv", str(venv_dir), "--python", python_version])
        else:
            _run([*_base_python(python_version), "-m", "venv", str(venv_dir)])

    python_exe = _venv_python(venv_dir)
    if not python_exe.exists():
        raise SystemExit(f"Runtime profile interpreter was not created: {python_exe}")

    if not uv:
        _run([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"])

    for step in provisioning.get("steps", []):
        if not isinstance(step, dict):
            raise SystemExit(f"Runtime profile {profile_id!r} contains an invalid provisioning step")
        packages = [str(value) for value in step.get("packages", [])]
        requirements = str(step.get("requirements", "")).strip()
        index_url = str(step.get("index_url", "")).strip()
        if uv:
            command = [uv, "pip", "install", "--python", str(python_exe)]
        else:
            command = [str(python_exe), "-m", "pip", "install"]
        if index_url:
            command.extend(["--index-url", index_url])
        if requirements:
            req_path = Path(requirements)
            if not req_path.is_absolute():
                req_path = PROJECT_ROOT / req_path
            command.extend(["-r", str(req_path.resolve())])
        command.extend(packages)
        if len(command) <= (5 if uv else 4):
            continue
        _run(command)

    actual = _interpreter_path(profile)
    if not actual.exists():
        raise SystemExit(
            f"Provisioning completed but profile interpreter does not match configuration: {actual}"
        )
    print(f"Runtime profile {profile_id!r} is installed at {actual}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage VoxPassport TTS runtime profiles")
    sub = parser.add_subparsers(dest="command", required=True)

    status_parser = sub.add_parser("status", help="Show whether a runtime profile is installed")
    status_parser.add_argument("profile_id")

    install_parser = sub.add_parser("install", help="Install a runtime profile")
    install_parser.add_argument("profile_id")

    repair_parser = sub.add_parser("repair", help="Recreate an isolated runtime profile")
    repair_parser.add_argument("profile_id")

    args = parser.parse_args()
    if args.command == "status":
        return status(args.profile_id)
    if args.command == "install":
        return install(args.profile_id)
    if args.command == "repair":
        return install(args.profile_id, repair=True)
    raise SystemExit("Unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())
