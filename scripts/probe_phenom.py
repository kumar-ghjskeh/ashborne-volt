"""Find the real job board behind Phenom career sites.

Phenom sites embed their first page of results (`phApp.ddo`) in the search
page HTML, and each job's `applyUrl` points at the employer's actual ATS —
usually a Workday tenant. That URL is all we need to connect the company with
an existing adapter.

    py scripts/probe_phenom.py
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
PATHS = ["/global/en/search-results", "/us/en/search-results", "/en/search-results",
         "/en-us/search-results", "/search-results", "/en/us/search-results"]
DDO = re.compile(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.", re.S)


def hosts(url: str) -> list[str]:
    h = urlparse(url).netloc.lower()
    root = ".".join(h.split(".")[-2:])
    out = []
    for c in (h, f"careers.{root}", f"jobs.{root}"):
        if c not in out:
            out.append(c)
    return out


def ats_of(url: str) -> str:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if host.endswith(".myworkdayjobs.com"):
        tenant, inst = host.split(".")[:2]
        seg = [p for p in u.path.split("/") if p]
        seg = [p for p in seg if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)]
        return f"workday\t{tenant}.{inst}/{seg[0] if seg else '?'}"
    if host.endswith(".icims.com"):
        return f"icims\t{host}"
    if "successfactors" in host or "sapsf" in host:
        return f"successfactors-native\t{host}"
    if host.endswith(".taleo.net"):
        return f"taleo\t{host}"
    if host.endswith(".oraclecloud.com"):
        return f"oracle\t{host}"
    return f"other\t{host}"


async def probe(client, name, url):
    for h in hosts(url):
        for p in PATHS:
            try:
                r = await client.get(f"https://{h}{p}", params={"keywords": "engineer"}, timeout=15)
            except Exception:
                continue
            if r.status_code != 200:
                continue
            m = DDO.search(r.text)
            if not m:
                continue
            try:
                d = json.loads(m.group(1))
            except Exception:
                continue
            data = (d.get("eagerLoadRefineSearch") or {})
            jobs = (data.get("data") or {}).get("jobs") or []
            urls = [j.get("applyUrl") for j in jobs if j.get("applyUrl")]
            if not urls:
                return f"{name}\tphenom-no-apply\t{h}{p}\t{data.get('totalHits')}"
            best = Counter(ats_of(u) for u in urls).most_common(1)[0][0]
            return f"{name}\t{best}\t(phenom {h}{p}, {data.get('totalHits')} hits)"
    return None


async def main():
    cfg = yaml.safe_load((ROOT / "config" / "companies.yaml").read_text(encoding="utf-8"))["companies"]
    todo = [(c["name"], c["careers_url"]) for c in cfg if not c.get("enabled")]
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}) as client:
        async def one(n, u):
            async with sem:
                return await probe(client, n, u)
        for r in await asyncio.gather(*(one(n, u) for n, u in todo)):
            if r:
                print(r, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
