from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_CLIENT_ROOTS = (
    PROJECT_ROOT / "apps" / "client",
    PROJECT_ROOT / "apps" / "desktop",
)


def _source_files(root: Path):
    if not root.exists():
        return []
    return [path for path in root.rglob("*") if path.is_file()]


def test_canonical_clients_do_not_add_fix_or_patch_layers():
    forbidden = []
    for root in CANONICAL_CLIENT_ROOTS:
        for path in _source_files(root):
            lowered = path.name.lower()
            if "-fixes." in lowered or "-patch." in lowered:
                forbidden.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert forbidden == [], (
        "Canonical client/desktop code must fix the owning implementation instead of "
        f"adding patch-history files: {forbidden}"
    )


def test_canonical_clients_do_not_use_legacy_iframe_eval_bridge():
    offenders = []
    for root in CANONICAL_CLIENT_ROOTS:
        for path in _source_files(root):
            if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".html"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "contentWindow" in text and ".eval(" in text:
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert offenders == [], f"Legacy iframe/eval bridge reintroduced in canonical client: {offenders}"


def test_desktop_shell_does_not_duplicate_product_screens():
    desktop = PROJECT_ROOT / "apps" / "desktop"
    forbidden_names = {
        "translator.tsx",
        "models.tsx",
        "voice-profiles.tsx",
        "settings.tsx",
        "studio.html",
    }
    duplicates = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in _source_files(desktop)
        if path.name.lower() in forbidden_names
    ]
    assert duplicates == [], (
        "apps/desktop must stay a thin native shell and consume apps/client rather than "
        f"duplicating product UI: {duplicates}"
    )


def test_repository_layout_document_exists():
    assert (PROJECT_ROOT / "docs" / "development" / "repository-layout.md").is_file()
