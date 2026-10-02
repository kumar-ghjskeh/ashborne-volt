"""Probe public job-board APIs for every candidate employer, with identity checks.

For each company, derive slug guesses from its name and domain and ask:
  * Greenhouse  boards-api.greenhouse.io/v1/boards/<slug>      (board name returned)
  * Lever       api.lever.co/v0/postings/<slug>?mode=json
  * Ashby       api.ashbyhq.com/posting-api/job-board/<slug>
  * Eightfold   <slug>.eightfold.ai/api/pcsx/search?domain=<domain>
  * SuccessFactors RMK  <careers host>/services/jobs/search (POST)

A hit is only printed as OK when the board identifies as the same company
(Greenhouse returns its board name); slug collisions with unrelated
organisations are printed as SUSPECT. Ashby/Lever expose no org name, so their
hits are always SUSPECT until a human glances at the titles printed beside them.

    py scripts/probe_boards.py config/candidates.tsv
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept": "application/json"}
NOISE = {"inc", "corp", "corporation", "company", "co", "group", "the", "llc", "of", "and", "usa", "us",
         "north", "america", "international", "technologies", "technology", "systems", "energy",
         "electric", "power", "solutions", "services", "engineering", "engineers"}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def slugs(name: str, url: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower().replace("&", " and "))]
    core = [w for w in words if w not in NOISE] or words
    host = urlparse(url).netloc.lower()
    dom = host.split(".")[-2] if host.count(".") >= 1 else host
    cands = [norm(name), "".join(core), core[0] if core else "", dom, f"{dom}careers",
             "-".join(core), "".join(words)]
    out, seen = [], set()
    for c in cands:
        if c and len(c) >= 3 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def same_company(name: str, label: str) -> bool:
    a, b = norm(name), norm(label)
    if not a or not b:
        return False
    core = norm("".join(w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in NOISE))
    return a in b or b in a or (core and (core in b or b in core))


async def probe(client: httpx.AsyncClient, name: str, url: str) -> list[str]:
    hits = []
    host = urlparse(url).netloc.lower()
    domain = ".".join(host.split(".")[-2:])
    for s in slugs(name, url):
        try:
            r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{s}", timeout=10)
            if r.status_code == 200:
                label = r.json().get("name", "")
                jr = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs", timeout=15)
                n = len(jr.json().get("jobs", [])) if jr.status_code == 200 else "?"
                tag = "OK " if same_company(name, label) else "SUS"
                hits.append(f"{tag} greenhouse:{s} ({label!r}, {n} jobs)")
        except Exception:
            pass
        try:
            r = await client.get(f"https://api.lever.co/v0/postings/{s}", params={"mode": "json", "limit": 3}, timeout=10)
            if r.status_code == 200 and isinstance(r.json(), list) and r.json():
                titles = [j.get("text", "") for j in r.json()[:3]]
                hits.append(f"SUS lever:{s} e.g. {titles}")
        except Exception:
            pass
        try:
            r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{s}", timeout=10)
            if r.status_code == 200 and r.json().get("jobs"):
                js = r.json()["jobs"]
                hits.append(f"SUS ashby:{s} ({len(js)} jobs) e.g. {[j.get('title') for j in js[:3]]}")
        except Exception:
            pass
        try:
            r = await client.get(f"https://{s}.eightfold.ai/api/pcsx/search",
                                 params={"domain": domain, "query": "engineer", "start": 0, "num": 1}, timeout=10)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                d = r.json()
                cnt = (d.get("data") or {}).get("count") if isinstance(d, dict) else None
                if cnt:
                    hits.append(f"OK  eightfold:{s} domain={domain} ({cnt} for 'engineer')")
        except Exception:
            pass
    # SuccessFactors RMK on the careers host
    for h in {host, f"careers.{domain}", f"jobs.{domain}"}:
        try:
            r = await client.post(f"https://{h}/services/jobs/search",
                                  json={"page": 0, "keywords": "engineer", "recordsperpage": 1, "startrow": 0,
                                        "filterquery": {}, "locationsearch": "", "sortby": "referencedate",
                                        "sortdir": "desc"},
                                  headers={**UA, "Origin": f"https://{h}", "Referer": f"https://{h}/jobs/"},
                                  timeout=10)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                d = r.json()
                total = d.get("totalJobs") or d.get("total") or len(d.get("jobSearchResult", []) or [])
                if total:
                    hits.append(f"OK  jobs2web:{h} ({total} for 'engineer')")
        except Exception:
            pass
    return hits


async def main(path: str) -> None:
    rows = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if ln.strip() and not ln.startswith("#"):
            f = ln.split("\t")
            if len(f) >= 6:
                rows.append((f[0], f[5]))
    sem = asyncio.Semaphore(6)
    async with httpx.AsyncClient(follow_redirects=True, headers=UA) as client:
        async def one(n, u):
            async with sem:
                return n, await probe(client, n, u)
        for coro in asyncio.as_completed([one(n, u) for n, u in rows]):
            n, hits = await coro
            for h in hits:
                print(f"{n}\t{h}", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "config/candidates.tsv"))
