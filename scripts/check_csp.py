"""Fail CI if the CSP in frontend/vercel.json no longer matches the built page.

The theme bootstrap in index.html is the only inline script, and the CSP allows
it by SHA-256. Edit that script without updating the hash and the theme stops
being applied before first paint, silently. This makes it loud instead.

    npm --prefix frontend run build && python scripts/check_csp.py
"""
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
cfg = json.loads((ROOT / "frontend" / "vercel.json").read_text(encoding="utf-8"))
csp = next(h["value"] for block in cfg["headers"] for h in block["headers"]
           if h["key"] == "Content-Security-Policy")

# Inline scripts only (no src=); tolerant of attributes and `</script >`.
inline = [body for attrs, body in re.findall(r"<script\b([^>]*)>(.*?)</script\s*>", html, re.S | re.I)
          if "src=" not in attrs.lower()]
missing = []
for body in inline:
    digest = "sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    if f"'{digest}'" not in csp:
        missing.append(digest)
if missing:
    print("CSP is missing hashes for inline scripts:", *missing, sep="\n  ")
    sys.exit(1)
print(f"CSP ok: {len(inline)} inline script(s) allowed by hash")
