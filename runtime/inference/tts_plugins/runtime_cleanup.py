"""Process-exit cleanup for supervisor-owned local TTS worker processes."""

from __future__ import annotations

import atexit

from runtime.inference.tts_plugins import runtime_supervisor as supervisor_module

_registered = False


def _cleanup_supervised_workers() -> None:
    supervisor = supervisor_module._DEFAULT_SUPERVISOR
    if supervisor is None:
        return
    for handle in list(supervisor._workers.values()):
        try:
            if handle.process.poll() is None:
                handle.process.terminate()
                try:
                    handle.process.wait(timeout=2)
                except Exception:
                    handle.process.kill()
                    try:
                        handle.process.wait(timeout=1)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            handle.log_file.close()
        except Exception:
            pass
    supervisor._workers.clear()


def register_runtime_cleanup() -> None:
    global _registered
    if _registered:
        return
    atexit.register(_cleanup_supervised_workers)
    _registered = True
