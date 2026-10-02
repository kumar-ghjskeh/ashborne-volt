"""Auto-discover a crackable public job API for every disabled company.

For each enabled:false company it derives slug/host candidates from the name +
careers_url and probes the major ATS APIs (Phenom, Greenhouse, Lever, Ashby,
SmartRecruiters). Reports, per company, the first platform that returns valid
job JSON (=> CRACKABLE on the 24/7 cloud), or Cloudflare-walled / nothing.

Read-only. Run:  py -m backend.scripts.discover_all
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402

from backend.app.config import load_all_companies  # noqa: E402

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
     "Accept": "application/json, text/html"}
TIMEOUT = 12
_SUFFIX = re.compile(r"\b(inc|corp|corporation|technologies|technology|semiconductor|semiconductors|"
                     r"solutions|computing|systems|company|labs|ltd|llc|group|holdings|the)\b", re.I)


def _cf(text: str) -> bool:
    return "just a moment" in text[:300].lower() or "cf-browser-verification" in text[:2000].lower()


def slug_candidates(name: str, careers_url: str) -> list[str]:
    base = _SUFFIX.sub("", name).strip()
    cands = []
    low = base.lower()
    cands.append(re.sub(r"[^a-z0-9]", "", low))           # siliconlabs
    cands.append(re.sub(r"[^a-z0-9]+", "-", low).strip("-"))  # silicon-labs
    cands.append(low.split()[0] if low.split() else low)  # silicon
    full = name.lower()
    cands.append(re.sub(r"[^a-z0-9]", "", full))
    host = urlparse(careers_url).netloc
    if host:
        parts = host.split(".")
        # e.g. www.qorvo.com -> qorvo ; boards.greenhouse.io/lattice handled elsewhere
        for p in parts:
            if p not in ("www", "com", "io", "net", "org", "careers", "jobs", "en", "co"):
                cands.append(p)
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c); out.append(c)
    return out[:5]


def get(url):
    try:
        r = httpx.get(url, headers=H, timeout=TIMEOUT, follow_redirects=True)
        return r
    except Exception:
        return None


def try_phenom(host):
    r = get(f"https://{host}/api/jobs?keywords=verification&page=1&limit=3")
    if r is None:
        return None
    if _cf(r.text):
        return "phenom:CLOUDFLARE"
    try:
        d = r.json()
        if isinstance(d, dict) and "jobs" in d:
            return f"PHENOM host={host} total={d.get('totalCount') or d.get('count')}"
    except Exception:
        pass
    return None


def try_greenhouse(slug):
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false")
    if r is None or r.status_code != 200:
        return None
    try:
        d = r.json()
        if isinstance(d, dict) and isinstance(d.get("jobs"), list) and d["jobs"]:
            return f"GREENHOUSE slug={slug} n={len(d['jobs'])}"
    except Exception:
        pass
    return None


def try_lever(slug):
    r = get(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=5")
    if r is None or r.status_code != 200:
        return None
    try:
        d = r.json()
        if isinstance(d, list) and d:
            return f"LEVER slug={slug} n={len(d)}"
    except Exception:
        pass
    return None


def try_ashby(slug):
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if r is None or r.status_code != 200:
        return None
    try:
        d = r.json()
        if isinstance(d, dict) and isinstance(d.get("jobs"), list) and d["jobs"]:
            return f"ASHBY slug={slug} n={len(d['jobs'])}"
    except Exception:
        pass
    return None


def try_smartrecruiters(slug):
    r = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=5")
    if r is None or r.status_code != 200:
        return None
    try:
        d = r.json()
        if isinstance(d, dict) and isinstance(d.get("content"), list) and d["content"]:
            return f"SMARTRECRUITERS slug={slug} total={d.get('totalFound')}"
    except Exception:
        pass
    return None


def main():
    companies = [c for c in load_all_companies() if not c.get("enabled")]
    print(f"Probing {len(companies)} disabled companies...\n")
    crackable, cloudflare, nothing = [], [], []
    for c in companies:
        name = c["name"]
        careers = c.get("careers_url", "")
        host = urlparse(careers).netloc
        slugs = slug_candidates(name, careers)
        hit = None
        cf_seen = False

        # Phenom on the careers host (and a careers.<slug>.com guess)
        phost_cands = [host] + [f"careers.{s}.com" for s in slugs[:2]]
        for ph in dict.fromkeys([h for h in phost_cands if h]):
            res = try_phenom(ph)
            if res and res.startswith("PHENOM"):
                hit = res; break
            if res and "CLOUDFLARE" in res:
                cf_seen = True
        # Slug-based ATSes
        if not hit:
            for s in slugs:
                for fn in (try_greenhouse, try_lever, try_ashby, try_smartrecruiters):
                    res = fn(s)
                    if res:
                        hit = res; break
                if hit:
                    break

        if hit:
            crackable.append((name, hit)); print(f"  [CRACK] {name:26} -> {hit}")
        elif cf_seen:
            cloudflare.append(name); print(f"  [CF]    {name:26} -> Cloudflare-walled Phenom")
        else:
            nothing.append(name); print(f"  [--]    {name:26} -> no public API found")

    print(f"\n==== {len(crackable)} crackable, {len(cloudflare)} cloudflare, {len(nothing)} none ====")
    print("CRACKABLE:", [n for n, _ in crackable])


if __name__ == "__main__":
    main()
