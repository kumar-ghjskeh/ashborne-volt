"""Now that curl_cffi (Chrome TLS impersonation) bypasses Cloudflare, RE-detect
the real ATS behind each CF-walled careers portal and find its job API.

For each company it fetches candidate careers hosts via curl_cffi, identifies the
ATS from HTML/JS signatures, and probes the matching JSON API (Phenom /api/jobs,
Workday CXS, Greenhouse, etc.). Read-only."""
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from curl_cffi import requests  # noqa: E402

# (name, [candidate careers hosts to try])
TARGETS = [
    ("TSMC", ["careers.tsmc.com"]),
    ("Ampere", ["careers.amperecomputing.com"]),
    ("Synaptics", ["careers.synaptics.com"]),
    ("Rambus", ["careers.rambus.com"]),
    ("Alphawave", ["careers.awaveip.com", "awaveip.com", "careers.alphawavesemi.com"]),
    ("Credo", ["careers.credosemi.com", "www.credosemi.com"]),
    ("Mythic", ["careers.mythic.ai", "mythic.ai"]),
    ("Blaize", ["careers.blaize.com", "www.blaize.com"]),
    ("Expedera", ["careers.expedera.com", "www.expedera.com"]),
    ("Collins Aerospace", ["careers.rtx.com"]),
]

SIGS = {
    "phenom": [r"phenom", r"/api/jobs"],
    "workday": [r"myworkdayjobs", r"/wday/cxs/"],
    "greenhouse": [r"boards\.greenhouse\.io", r"greenhouse"],
    "lever": [r"jobs\.lever\.co", r"api\.lever\.co"],
    "icims": [r"icims\.com"],
    "smartrecruiters": [r"smartrecruiters"],
    "jobvite": [r"jobvite"],
    "eightfold": [r"eightfold\.ai"],
    "avature": [r"avature"],
    "successfactors": [r"successfactors", r"jobs\.sap\.com"],
}


def fetch(url):
    try:
        return requests.get(url, impersonate="chrome", timeout=25, headers={
            "Accept": "text/html,application/json"})
    except Exception as e:
        return e


def detect(html):
    found = {}
    low = html.lower()
    for ats, pats in SIGS.items():
        for p in pats:
            m = re.findall(p, low)
            if m:
                found[ats] = found.get(ats, 0) + len(m)
    return found


def main():
    for name, hosts in TARGETS:
        print(f"\n=== {name} ===")
        for host in hosts:
            r = fetch(f"https://{host}/")
            if isinstance(r, Exception):
                print(f"   {host}: ERR {type(r).__name__}")
                continue
            cf = "just a moment" in r.text[:300].lower()
            ats = detect(r.text)
            # pull a careerSiteUrl / api hint
            apihint = re.findall(r"https?://[a-z0-9.\-]+/(?:api/jobs|wday/cxs/[^\"' ]+)", r.text[:200000], re.I)
            print(f"   {host}: [{r.status_code}] cf={cf} ats={ats} "
                  f"final={urlparse(str(r.url)).netloc}")
            if apihint:
                print(f"        apihint: {list(dict.fromkeys(apihint))[:3]}")
            # If Phenom signature, probe /api/jobs on the FINAL host via curl_cffi
            if "phenom" in ats or "/api/jobs" in r.text.lower():
                fh = urlparse(str(r.url)).netloc or host
                pr = fetch(f"https://{fh}/api/jobs?keywords=verification&page=1&limit=3")
                if not isinstance(pr, Exception):
                    isj = "json" in pr.headers.get("content-type", "")
                    n = "-"
                    if isj:
                        try:
                            n = len(pr.json().get("jobs", []))
                        except Exception:
                            isj = False
                    print(f"        -> {fh}/api/jobs [{pr.status_code}] json={isj} jobs={n}")
                break


if __name__ == "__main__":
    main()
