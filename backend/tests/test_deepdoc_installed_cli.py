from __future__ import annotations

import subprocess
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_installed_deepdoc_cli_runs_in_temp_venv():
    script = BACKEND_ROOT / ".tmp_deepdoc_venv" / "Scripts" / "deepdoc.exe"
    if not script.exists():
        return

    completed = subprocess.run(
        [str(script), "capabilities"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert '"pdf_modes"' in completed.stdout


def test_installed_deepdoc_doctor_runs_in_temp_venv():
    script = BACKEND_ROOT / ".tmp_deepdoc_venv" / "Scripts" / "deepdoc.exe"
    if not script.exists():
        return

    completed = subprocess.run(
        [str(script), "doctor"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert '"runtime_dependencies"' in completed.stdout
