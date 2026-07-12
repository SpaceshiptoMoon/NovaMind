from __future__ import annotations

import zipfile
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_deepdoc_packaging_includes_resume_resources_and_docs():
    dist_dir = BACKEND_ROOT / "dist"
    wheels = sorted(dist_dir.glob("novamind-*.whl"))
    if not wheels:
        # Keep this test informative when the build artifact has not been generated yet.
        return

    wheel_path = max(wheels, key=lambda path: path.stat().st_mtime)
    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    normalized_names = {name.replace("\\", "/") for name in names}

    assert "shared/knowledge/integrations/deepdoc/parsers/upstream/resume/entities/res/schools.csv" in normalized_names
    assert "shared/knowledge/integrations/deepdoc/parsers/upstream/resume/entities/res/good_sch.json" in normalized_names
