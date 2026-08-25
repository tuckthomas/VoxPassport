from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_CLIENT_ROOT = PROJECT_ROOT / "apps" / "client"
DESKTOP_COMPANION_ROOT = PROJECT_ROOT / "apps" / "desktop-companion"


def _source_files(root: Path):
    if not root.exists():
        return []
    return [path for path in root.rglob("*") if path.is_file()]


def test_canonical_client_does_not_add_fix_or_patch_layers():
    forbidden = []
    for path in _source_files(CANONICAL_CLIENT_ROOT):
        lowered = path.name.lower()
        if "-fixes." in lowered or "-patch." in lowered:
            forbidden.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert forbidden == [], (
        "Canonical Expo client code must fix the owning implementation instead of "
        f"adding patch-history files: {forbidden}"
    )


def test_canonical_client_does_not_use_legacy_iframe_eval_bridge():
    offenders = []
    for path in _source_files(CANONICAL_CLIENT_ROOT):
        if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".html"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "contentWindow" in text and ".eval(" in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert offenders == [], f"Legacy iframe/eval bridge reintroduced in canonical Expo client: {offenders}"


def test_legacy_desktop_product_ui_is_removed():
    manager = DESKTOP_COMPANION_ROOT / "model-manager"
    manager_files = {
        path.relative_to(manager).as_posix()
        for path in _source_files(manager)
    }
    assert manager_files <= {"index.html"}, (
        "apps/desktop-companion/model-manager may contain only the temporary Expo launcher; "
        f"legacy product UI files returned: {sorted(manager_files - {'index.html'})}"
    )
    launcher = manager / "index.html"
    if launcher.exists():
        text = launcher.read_text(encoding="utf-8")
        assert "127.0.0.1:8081" in text
        assert "studio" not in text.lower()
    assert not (DESKTOP_COMPANION_ROOT / "overlay").exists(), (
        "The duplicate desktop overlay was retired; browser-specific overlays belong in apps/browser-extension"
    )


def test_no_legacy_fix_layers_remain_in_desktop_companion():
    offenders = []
    for path in _source_files(DESKTOP_COMPANION_ROOT):
        lowered = path.name.lower()
        if "-fixes." in lowered or "-patch." in lowered:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert offenders == [], f"Legacy desktop patch layers returned: {offenders}"


def test_no_dedicated_tauri_desktop_shell_is_present():
    desktop = PROJECT_ROOT / "apps" / "desktop"
    assert not desktop.exists(), (
        "apps/desktop reintroduces the rejected Tauri/dedicated desktop-shell architecture; "
        "desktop-native audio belongs behind runtime/native service contracts while apps/client remains Expo"
    )


def test_expo_client_has_no_tauri_dependency_or_bridge():
    package_json = (CANONICAL_CLIENT_ROOT / "package.json").read_text(encoding="utf-8")
    assert "@tauri-apps/" not in package_json
    tauri_references = []
    for path in _source_files(CANONICAL_CLIENT_ROOT):
        if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "__TAURI" in text or "@tauri-apps/" in text:
            tauri_references.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert tauri_references == [], f"Tauri references found in Expo client: {tauri_references}"


def test_repository_layout_document_exists():
    assert (PROJECT_ROOT / "docs" / "development" / "repository-layout.md").is_file()
