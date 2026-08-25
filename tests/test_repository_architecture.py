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


def test_legacy_desktop_companion_is_fully_removed():
    assert not DESKTOP_COMPANION_ROOT.exists(), (
        "apps/desktop-companion is retired. Product UI and reusable branding belong under "
        "apps/client; browser-specific integration belongs under apps/browser-extension."
    )


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


def test_canonical_brand_assets_exist():
    assets = CANONICAL_CLIENT_ROOT / "assets"
    assert (assets / "VoxPassport_icon_1024.png").is_file()
    assert (assets / "VoxPassport_icon_256.png").is_file()
    assert (assets / "VoxPassport_icon.svg").is_file()


def test_repository_layout_document_exists():
    assert (PROJECT_ROOT / "docs" / "development" / "repository-layout.md").is_file()
