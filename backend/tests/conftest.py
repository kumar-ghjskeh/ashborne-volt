"""Make both import styles work: ``app.*`` (from backend/) and ``backend.app.*``
(from the repo root, which is how the workflows run the code)."""

import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
for p in (_BACKEND, _BACKEND.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Legacy endpoint tests call routes the public allowlist hides. The allowlist
# itself is tested explicitly in test_api_security.py.
os.environ.setdefault("ENFORCE_ROUTE_ALLOWLIST", "false")
