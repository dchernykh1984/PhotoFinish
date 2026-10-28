"""The frozen app's layout: PyInstaller runs the entry script from the bundle root.

A build unpacks the program into one folder, runs app/main.py there as main.py,
and ships package data such as the icon under app/ (build.yml: --add-data
app/app.ico:app). An icon resolved next to the entry script is then missing,
and silently so: a QIcon of a missing file is just empty.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_icon_is_found_when_main_runs_from_the_bundle_root(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(
        ROOT / "app", bundle / "app", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copy(ROOT / "app" / "main.py", bundle / "main.py")
    probe = (
        "import runpy, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(bundle)!r})\n"
        f"names = runpy.run_path({str(bundle / 'main.py')!r}, run_name='probe')\n"
        "icon = names['_ICON']\n"
        "print(Path(icon).is_file())\n"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=True,
    )
    assert result.stdout.strip() == "True"
