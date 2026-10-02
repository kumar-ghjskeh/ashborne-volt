"""Find Jibe/iCIMS-Attract job boards by probing `/api/jobs` on careers hosts.

Many large employers' careers sites (careers.X.com, jobs.X.com) serve a public
JSON job API at /api/jobs. Rendering pages to find them is slow and misses most;
a direct probe of a few host variants per company is fast and precise.

    py scripts/probe_jibe.py config/candidates.tsv
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def hosts_for(careers_url: str) -> list[str]:
    host = urlparse(careers_url).netloc.lower()
    labels = host.split(".")
    root = ".".join(labels[-2:]) if len(labels) >= 2 else host
    out = [host, f"careers.{root}", f"jobs.{root}", f"careers.{root.split('.')[0]}.com"]
    seen, uniq = set(), []
    for h in out:
        if h and h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


async def probe(client: httpx.AsyncClient, name: str, url: str) -> str | None:
    for host in hosts_for(url):
        api = f"https://{host}/api/jobs"
        try:
            r = await client.get(api, params={"page": 1, "limit": 1}, headers=UA, timeout=12)
        except Exception:
            continue
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            continue
        try:
            d = r.json()
        except Exception:
            continue
        if isinstance(d, dict) and "jobs" in d and "totalCount" in d:
            return f"{name}\t{host}\t{d.get('totalCount')}"
    return None


async def main(path: str) -> None:
    rows = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        f = ln.split("\t")
        if len(f) >= 6:
            rows.append((f[0], f[5]))
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        async def one(n, u):
            async with sem:
                return await probe(client, n, u)
        results = await asyncio.gather(*(one(n, u) for n, u in rows))
    for r in results:
        if r:
            print(r, flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "config/candidates.tsv"))
