"""Verify every configured company's ATS endpoint returns live data.

Run:  py scripts/verify_sources.py
Outputs a table of WORKING / BROKEN sources so config can be corrected.
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "companies.yaml"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _req(url: str, body: dict | None = None, base: str | None = None):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        if base:
            headers["Origin"] = base
            headers["Referer"] = base + "/"
    req = urllib.request.Request(url, headers=headers)
    if body is not None:
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa
        return "ERR:" + type(e).__name__, b""


def check_greenhouse(c):
    board = c.get("greenhouse_board", "")
    s, body = _req(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
    if s == 200:
        return True, len(json.loads(body).get("jobs", [])), board
    return False, s, board


def check_lever(c):
    slug = c.get("lever_slug") or c.get("lever_company", "")
    s, body = _req(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if s == 200:
        return True, len(json.loads(body)), slug
    return False, s, slug


def check_ashby(c):
    org = c.get("ashby_org", "")
    s, body = _req(f"https://api.ashbyhq.com/posting-api/job-board/{org}")
    if s == 200:
        return True, len(json.loads(body).get("jobs", [])), org
    return False, s, org


def check_workday(c):
    t = c.get("workday_tenant", "")
    i = c.get("workday_instance", "wd1")
    site = c.get("workday_career_site", "External")
    base = f"https://{t}.{i}.myworkdayjobs.com"
    url = f"{base}/wday/cxs/{t}/{site}/jobs"
    body = {"limit": 20, "offset": 0, "searchText": "", "appliedFacets": {}}
    s, b = _req(url, body, base)
    if s == 200:
        try:
            return True, json.loads(b).get("total", "?"), f"{t}/{i}/{site}"
        except Exception:
            return False, "badjson", f"{t}/{i}/{site}"
    return False, s, f"{t}/{i}/{site}"


CHECKERS = {
    "greenhouse": check_greenhouse,
    "lever": check_lever,
    "ashby": check_ashby,
    "workday": check_workday,
}


def main():
    data = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    companies = data.get("companies", [])
    ok, broken, skipped = [], [], []
    for c in companies:
        ats = c.get("ats_platform", "generic").lower()
        name = c["name"]
        checker = CHECKERS.get(ats)
        if not checker:
            skipped.append((name, ats))
            continue
        good, info, detail = checker(c)
        line = f"{'OK ' if good else 'XX '}{name:28} {ats:11} {str(info):>6}  {detail}"
        print(line)
        (ok if good else broken).append((name, ats, info, detail))
        time.sleep(0.5)

    print("\n" + "=" * 60)
    print(f"WORKING: {len(ok)}   BROKEN: {len(broken)}   "
          f"NON-API (skipped): {len(skipped)}")
    print("\nBROKEN (need fix or disable):")
    for n, a, i, d in broken:
        print(f"  - {n} [{a}] {i}  ({d})")
    print("\nNON-API companies (will be disabled):")
    for n, a in skipped:
        print(f"  - {n} [{a}]")


if __name__ == "__main__":
    sys.exit(main())
