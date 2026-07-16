from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Make `novamind` importable via the src-side namespace package
# (backend/src/novamind/) without relying on the legacy backend/novamind
# dev-bridge shim, which has been removed. The real code lives under
# backend/src/{core,features,setting,shared}; the inner novamind package
# re-exports them as novamind.<name>.
SOURCE_ROOT = BACKEND_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
