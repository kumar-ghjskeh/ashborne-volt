"""Auto-discover the correct ATS endpoint for companies.

For each name, probe Greenhouse / Lever / Ashby with several slug variants
and report any that return live jobs. Use to repair companies.yaml.

Run:  py scripts/discover_sources.py
"""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"

# Companies to discover (broken or non-API), with optional manual hints
TARGETS = [
    "Groq", "Cerebras Systems", "SambaNova Systems", "SiFive",
    "Esperanto Technologies", "Ventana Micro Systems", "Untether AI",
    "Eliyan", "Enfabrica", "Celestial AI", "Achronix", "MaxLinear",
    "Credo Semiconductor", "Ayar Labs", "Cornelis Networks", "Synaptics",
    "Arista Networks", "Rambus", "Alphawave Semi", "Cisco",
    "Lattice Semiconductor", "Keysight Technologies", "Cadence",
    "Tenstorrent", "Astera Labs", "Lightmatter", "Rivos", "Axelera AI",
    "EnCharge AI", "Positron", "MatX", "Lemurian Labs", "Baya Systems",
    "SiMa.ai", "Recogni", "Mythic", "Blaize", "Flex Logix", "Quadric",
    "Expedera", "Tesla", "Ampere Computing", "Tenstorrent", "Ambarella",
]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


def slug_variants(name: str):
    base = name.lower()
    base = re.sub(r"[^a-z0-9 ]", "", base)
    words = base.split()
    stop = {"systems", "technologies", "semiconductor", "semiconductors",
            "labs", "inc", "micro", "ai", "networks", "the"}
    core = [w for w in words if w not in stop]
    variants = {
        "".join(words),
        "".join(core),
        "-".join(words),
        "-".join(core),
        words[0],
        core[0] if core else words[0],
    }
    return [v for v in variants if v]


def probe(name):
    hits = []
    for slug in slug_variants(name):
        # Greenhouse
        s, b = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if s == 200:
            n = len(json.loads(b).get("jobs", []))
            if n:
                hits.append(("greenhouse", slug, n))
        time.sleep(0.25)
        # Lever
        s, b = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if s == 200:
            try:
                n = len(json.loads(b))
                if n:
                    hits.append(("lever", slug, n))
            except Exception:
                pass
        time.sleep(0.25)
        # Ashby
        s, b = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if s == 200:
            try:
                n = len(json.loads(b).get("jobs", []))
                if n:
                    hits.append(("ashby", slug, n))
            except Exception:
                pass
        time.sleep(0.25)
    return hits


def main():
    for name in TARGETS:
        hits = probe(name)
        if hits:
            best = ", ".join(f"{ats}:{slug}={n}" for ats, slug, n in hits)
            print(f"OK  {name:26} -> {best}")
        else:
            print(f"XX  {name:26} -> none")


if __name__ == "__main__":
    main()
