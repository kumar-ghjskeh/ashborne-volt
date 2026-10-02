"""Find SAP SuccessFactors career sites (`/search/?q=` with `jobTitle-link` rows)
for catalog companies that are not connected yet.

    py scripts/probe_successfactors.py
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]


def hosts(url: str) -> list[str]:
    h = urlparse(url).netloc.lower()
    root = ".".join(h.split(".")[-2:])
    out = []
    for c in (h, f"careers.{root}", f"jobs.{root}", f"career.{root}", f"careers-{root.split('.')[0]}.com"):
        if c not in out:
            out.append(c)
    return out


async def probe(client, name, url):
    for h in hosts(url):
        try:
            r = await client.get(f"https://{h}/search/", params={"q": "engineer"}, timeout=12)
        except Exception:
            continue
        if r.status_code == 200 and "jobTitle-link" in r.text:
            m = re.search(r"of <b>(\d+)</b>", r.text)
            return f"{name}\t{h}\t{m.group(1) if m else '?'}"
    return None


async def main():
    cfg = yaml.safe_load((ROOT / "config" / "companies.yaml").read_text(encoding="utf-8"))["companies"]
    todo = [(c["name"], c["careers_url"]) for c in cfg if not c.get("enabled")]
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        async def one(n, u):
            async with sem:
                return await probe(client, n, u)
        for r in await asyncio.gather(*(one(n, u) for n, u in todo)):
            if r:
                print(r, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
