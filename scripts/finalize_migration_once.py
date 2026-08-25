from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: Path, old: str, new: str, *, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise SystemExit(f"{path}: expected {count} occurrence(s), found {found}: {old[:120]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


main = ROOT / "runtime/inference/server/main.py"
old_static = '''        companion_dir = PROJECT_ROOT / "apps" / "desktop-companion"
        assets_dir = companion_dir / "assets"
        manager_dir = companion_dir / "model-manager"
        overlay_dir = companion_dir / "overlay"
        if assets_dir.exists():
            app.router.add_static("/assets", path=str(assets_dir), show_index=False)
        if manager_dir.exists():
            app.router.add_static("/manager", path=str(manager_dir), show_index=True)
        if overlay_dir.exists():
            app.router.add_static("/overlay", path=str(overlay_dir), show_index=True)

        async def index_redirect(request):
            raise web.HTTPFound("/manager/index.html")
        app.router.add_get("/", index_redirect)
'''
new_static = '''        async def index_redirect(request):
            # The runtime is API/media infrastructure; the canonical product UI is Expo.
            raise web.HTTPFound("http://127.0.0.1:8081/")
        app.router.add_get("/", index_redirect)
'''
replace_exact(main, old_static, new_static)

integrated = ROOT / "runtime/inference/server/integrated_main.py"
replace_exact(
    integrated,
    "This composes the legacy inference/control daemon with the new provider-neutral\n",
    "This composes the core inference/control runtime with the provider-neutral\n",
)

plan = ROOT / ".agents/plans/in-progress/universal-expo-client-cloud-architecture-plan.md"
replace_exact(
    plan,
    "Status: In progress — canonical Expo migration, hosted macOS HAL validation, account/auth, and source-level desktop/live-audio implementation are substantially complete. Remaining work is primarily Windows WDK build completion plus physical Windows/macOS/conferencing validation and explicitly deferred hosted/mobile features. Tauri is not part of the architecture.",
    "Status: In progress — canonical Expo migration, account/auth foundations, cross-platform native desktop audio, hosted Windows WDK build/staging, hosted macOS HAL crossover, and headless Linux PipeWire crossover are complete. Remaining current-phase work is physical Windows/macOS/conferencing acceptance plus explicitly deferred hosted/mobile features. Tauri is not part of the architecture.",
)
replace_exact(
    plan,
    "- [ ] Build/sign/install the Windows virtual driver on the development Windows machine.",
    "- [x] Build/sign/stage the Windows virtual driver in hosted WDK-capable CI.\n- [ ] Test-sign/install the staged Windows virtual driver on the development Windows machine under its allowed driver policy.",
)
replace_exact(
    plan,
    "- [x] Retire the prototype `apps/desktop-companion/model-manager` product UI after Expo parity; only a temporary `/manager` -> Expo compatibility launcher and reusable brand assets remain.",
    "- [x] Retire the prototype `apps/desktop-companion/model-manager` product UI after Expo parity.",
)
replace_exact(
    plan,
    "- [ ] Remove the final temporary `apps/desktop-companion` compatibility launcher/assets after the runtime root route no longer references `/manager`.",
    "- [x] Remove `apps/desktop-companion` entirely after moving reusable brand assets to `apps/client/assets` and changing the runtime root route to the canonical Expo client.",
)
replace_exact(
    plan,
    "- [ ] Compile the Windows kernel driver fully with WDK on the Windows development machine or WDK-capable CI runner.",
    "- [x] Compile the Windows kernel driver fully with WDK on the hosted Windows CI runner and verify the staged INF/SYS package.",
)
replace_exact(
    plan,
    "- [ ] Complete the hosted Windows WDK kernel-driver compile and staged INF/SYS verification.",
    "- [x] Complete the hosted Windows WDK kernel-driver compile and staged INF/SYS verification.",
)
replace_exact(
    plan,
    "- [ ] Make the headless Linux helper crossover validation green after the PipeWire-Pulse media-boundary change.",
    "- [x] Make the headless Linux helper crossover validation green after the PipeWire-Pulse media-boundary change.",
)

# The final tree must not retain the one-shot migration machinery.
(ROOT / "scripts/finalize_migration_once.py").unlink()
(ROOT / ".github/workflows/finalize-migration-once.yml").unlink()
