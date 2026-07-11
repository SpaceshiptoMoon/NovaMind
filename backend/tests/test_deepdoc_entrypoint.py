from __future__ import annotations

import zipfile
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_deepdoc_console_script_is_present_in_wheel():
    dist_dir = BACKEND_ROOT / "dist"
    wheels = sorted(dist_dir.glob("novamind-*.whl"))
    if not wheels:
        return

    wheel_path = max(wheels, key=lambda path: path.stat().st_mtime)
    with zipfile.ZipFile(wheel_path) as wheel:
        entrypoint_files = [name for name in wheel.namelist() if name.endswith("entry_points.txt")]

        assert entrypoint_files
        payload = wheel.read(entrypoint_files[0]).decode("utf-8")

    assert "[console_scripts]" in payload
    assert "deepdoc = shared.utils.deepdoc.__main__:main" in payload
