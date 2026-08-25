from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / ".agents/plans/in-progress/universal-expo-client-cloud-architecture-plan.md"
README = ROOT / "README.md"


def replace_exact(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    PLAN,
    "- [x] Add deployment configuration through `config/deployment.json` plus real `.env` loading.",
    "- [x] Add deployment configuration through `configs/deployment.json` plus real `.env` loading.",
)
replace_exact(
    PLAN,
    "- [x] Add `VOXPASSPORT_LOCAL_ONLY`, `VOXPASSPORT_ACCOUNTS_ENABLED`, and `VOXPASSPORT_ABUSE_CONTROLS_ENABLED` semantics.",
    "- [x] Add `VOXPASSPORT_LOCAL_ONLY`, `VOXPASSPORT_AUTH_ENABLED`, and `VOXPASSPORT_ABUSE_CONTROLS_ENABLED` semantics.",
)
replace_exact(
    PLAN,
    "- [ ] Remove the remaining temporary `apps/desktop-companion` URL-compatibility launcher/assets after the runtime `/manager` redirect is eliminated.",
    "- [x] Remove the remaining `apps/desktop-companion` compatibility launcher/assets after eliminating the runtime `/manager` redirect and moving reusable branding to `apps/client/assets`.",
)
replace_exact(
    README,
    "- [Repository Layout and Ownership](docs/development/repository-layout.md)\n",
    "- [Repository Layout and Ownership](docs/development/repository-layout.md)\n- [Configuration](configs/README.md)\n",
)

# Self-delete the one-shot migration machinery from the final tree.
(ROOT / "scripts/final_plan_doc_fix_once.py").unlink()
(ROOT / ".github/workflows/final-plan-doc-fix-once.yml").unlink()
