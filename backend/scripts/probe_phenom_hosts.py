"""Batch-probe candidate semiconductor careers hosts for a cloud-reachable
Phenom (/api/jobs) or iCIMS JSON API — find more companies the new adapters can
unlock 24/7 without a browser."""
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
     "Accept": "application/json, text/html"}

# (company, careers host candidates)
CANDIDATES = [
    ("Texas Instruments", ["careers.ti.com"]),
    ("Renesas", ["careers.renesas.com"]),
    ("Skyworks", ["careers.skyworksinc.com", "jobs.skyworksinc.com"]),
    ("Qorvo", ["careers.qorvo.com", "jobs.qorvo.com"]),
    ("onsemi", ["careers.onsemi.com"]),
    ("Lattice", ["careers.latticesemi.com"]),
    ("Silicon Labs", ["careers.silabs.com"]),
    ("Cirrus Logic", ["careers.cirrus.com", "jobs.cirrus.com"]),
    ("Ambarella", ["careers.ambarella.com"]),
    ("Teradyne", ["careers.teradyne.com"]),
    ("Keysight", ["careers.keysight.com"]),
    ("Rambus", ["careers.rambus.com"]),
    ("Synaptics", ["careers.synaptics.com"]),
    ("Western Digital", ["careers.westerndigital.com", "jobs.westerndigital.com"]),
    ("Wolfspeed", ["careers.wolfspeed.com"]),
    ("Microchip", ["careers.microchip.com"]),
    ("NXP", ["careers.nxp.com"]),
    ("Qualcomm", ["careers.qualcomm.com"]),
]


def probe(host: str):
    # Phenom
    try:
        r = httpx.get(f"https://{host}/api/jobs", params={"keywords": "verification", "page": 1, "limit": 5},
                      headers=H, timeout=20, follow_redirects=True)
        ct = r.headers.get("content-type", "")
        if r.status_code == 200 and "json" in ct:
            try:
                d = r.json()
                if isinstance(d, dict) and "jobs" in d:
                    return f"PHENOM ok totalCount={d.get('totalCount') or d.get('count')}"
            except Exception:
                pass
        tag = "CF" if "just a moment" in r.text[:200].lower() else ("html" if "html" in ct else ct)
        return f"phenom={r.status_code}/{tag}"
    except Exception as e:
        return f"phenom-ERR {type(e).__name__}"


def main():
    for name, hosts in CANDIDATES:
        results = []
        for h in hosts:
            results.append(f"{h}: {probe(h)}")
        print(f"{name:20} | " + " || ".join(results))


if __name__ == "__main__":
    main()
