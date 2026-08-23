"""Process-exit cleanup for supervisor-owned local TTS processes."""

from __future__ import annotations

import atexit

from runtime.inference.tts_plugins import runtime_supervisor as supervisor_module

_registered = False


def _cleanup_handle(handle) -> None:
    try:
        supervisor_module.TtsRuntimeSupervisor._terminate_process_tree_blocking(handle.process)
    except Exception:
        pass
    try:
        handle.log_file.close()
    except Exception:
        pass


def _cleanup_supervised_workers() -> None:
    supervisor = supervisor_module._DEFAULT_SUPERVISOR
    if supervisor is None:
        return
    # Proxy backends may own the actual GPU model, so they are as important to
    # terminate as the generic protocol workers during abnormal/interpreter exit.
    for handle in list(supervisor._backends.values()):
        _cleanup_handle(handle)
    for handle in list(supervisor._workers.values()):
        _cleanup_handle(handle)
    supervisor._backends.clear()
    supervisor._workers.clear()


def register_runtime_cleanup() -> None:
    global _registered
    if _registered:
        return
    atexit.register(_cleanup_supervised_workers)
    _registered = True
