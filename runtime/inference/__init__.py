import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
_packages_dir = _project_root / "packages"

if str(_packages_dir) not in sys.path:
    sys.path.insert(0, str(_packages_dir))
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
