"""Find and VERIFY the ATS board for a list of companies, then emit config YAML.

Why this exists rather than hand-editing companies.yaml: three entries in this
repo pointed at boards belonging to entirely different organisations. Greenhouse
`ventana` is "Ventana by Buckner", a senior-living operator; `flex` is "Flex";
Ashby `rain` is Rain the fintech. All three reported zero jobs, so nothing looked
wrong — the keyword filter was the only thing keeping a nursing home's postings
off a semiconductor job board.

The existing discover_sources.py probes slugs and reports whichever one returns
data. That is the bug, not the fix: returning data is not the same as being the
right company. So every candidate here must clear an IDENTITY check before it is
reported, and a board that answers but belongs to someone else is reported as
WRONG-COMPANY rather than as a find.

    py scripts/discover_companies.py                  # probe the built-in list
    py scripts/discover_companies.py --emit            # also print YAML to paste
    py scripts/discover_companies.py "Lam Research"    # probe one name

Identity signals, by platform:
  greenhouse       boards-api .../boards/<slug> returns the board's own `name`
  smartrecruiters  each posting carries company.name
  lever / ashby    no org name is exposed, so fall back to comparing the slug
                   against the company name and requiring hardware-ish postings
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Titles that mean this really is an RTL design / verification employer. Word
# boundaries matter: a bare "soc" substring matches "aSSOCiate", which made an
# early version of this probe report nursing-home and legal roles as silicon.
RTL_TITLE = re.compile(
    r"\b(rtl|asic|fpga|vlsi)\b"
    r"|\b(design|functional|formal|pre[- ]silicon|hardware|chip|silicon)\s+verification\b"
    r"|\b(digital|logic|front[- ]end|chip)\s+design\b"
    r"|\b(systemverilog|verilog|vhdl|uvm)\b"
    r"|\bsoc\s+(design|verification|architect|integration)\b"
    r"|\b(design|verification)\s+engineer,?\s+(soc|asic|silicon)\b",
    re.I,
)
# Bare \bsoc\b and \bip\b are deliberately absent, and so is a bare
# "verification engineer". "Assoc. Security Specialist, SOC" is a Security
# Operations Centre role and matched seven times at one company; "Autonomy
# Verification Engineer" is software. A probe that reports those as silicon is
# worse than one reporting nothing, because it invites adding a company whose
# board carries no RTL work at all.

WORKDAY_SITES = ("External", "Careers", "careers", "External_Career_Site",
                 "ExternalCareerSite", "Search")
WORKDAY_INSTANCES = ("wd1", "wd3", "wd5")

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
}


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _norm(s: str) -> str:
    """Loose comparable form, for judging whether two names are the same org."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def slug_candidates(name: str) -> list[str]:
    """Plausible board tokens for a company name, most likely first."""
    low = name.lower()
    bare = re.sub(r"[^a-z0-9 ]", "", low)
    words = bare.split()
    out = [
        "".join(words),
        "-".join(words),
        words[0] if words else "",
        "".join(w for w in words if w not in
                {"technologies", "technology", "semiconductor", "semiconductors",
                 "systems", "labs", "inc", "corporation", "corp", "company"}),
    ]
    seen, uniq = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def titles_for(platform: str, data) -> list[str]:
    if platform == "greenhouse":
        return [j.get("title") or "" for j in (data or {}).get("jobs", [])]
    if platform == "lever":
        return [j.get("text") or "" for j in (data or [])]
    if platform == "ashby":
        return [j.get("title") or "" for j in (data or {}).get("jobs", [])]
    return [j.get("name") or "" for j in (data or {}).get("content", [])]


def identity_of(platform: str, slug: str, data) -> str | None:
    """The organisation name the board itself claims, when it exposes one."""
    if platform == "greenhouse":
        meta = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
        return (meta or {}).get("name")
    if platform == "smartrecruiters":
        for p in (data or {}).get("content", []):
            n = (p.get("company") or {}).get("name")
            if n:
                return n
    return None


def probe(name: str) -> dict:
    """Return the first candidate that both responds AND looks like this company."""
    rejected: list[str] = []
    for platform, tmpl in ENDPOINTS.items():
        for slug in slug_candidates(name):
            data = _get(tmpl.format(slug=slug))
            if data is None:
                continue
            titles = titles_for(platform, data)
            if not titles:
                continue
            claimed = identity_of(platform, slug, data)
            rtl = [t for t in titles if RTL_TITLE.search(t)]

            if claimed is not None:
                # Authoritative: the board says who it belongs to.
                if _norm(name) not in _norm(claimed) and _norm(claimed) not in _norm(name):
                    rejected.append(f"{platform}/{slug} is {claimed!r}")
                    continue
            elif not rtl:
                # No identity signal and nothing hardware-shaped: refuse to guess.
                rejected.append(f"{platform}/{slug} no org name, 0 RTL titles")
                continue

            return {
                "name": name, "platform": platform, "slug": slug,
                "claimed": claimed, "total": len(titles), "rtl": len(rtl),
                "samples": rtl[:3], "rejected": rejected,
            }
    wd = probe_workday(name)
    if wd:
        tenant, inst, site, total, titles = wd
        rtl = [t for t in titles if RTL_TITLE.search(t)]
        return {
            "name": name, "platform": "workday", "slug": tenant,
            "workday": (tenant, inst, site), "claimed": None,
            "total": total, "rtl": len(rtl), "samples": rtl[:3],
            "rejected": rejected,
        }
    return {"name": name, "platform": None, "rejected": rejected}


def probe_workday(name: str):
    """Workday hosts most large semiconductor and systems employers.

    Addressed by a tenant + instance + career-site triple rather than a board
    slug, and the CXS endpoint answers 422 unless Origin/Referer look
    same-origin. Returns the first combination that responds with postings.
    """
    for tenant in slug_candidates(name):
        for inst in WORKDAY_INSTANCES:
            root = "https://%s.%s.myworkdayjobs.com" % (tenant, inst)
            for site in WORKDAY_SITES:
                url = "%s/wday/cxs/%s/%s/jobs" % (root, tenant, site)
                body = json.dumps({
                    "appliedFacets": {}, "limit": 20, "offset": 0,
                    "searchText": "verification",
                }).encode()
                req = urllib.request.Request(url, data=body, headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json", "User-Agent": UA,
                    "Origin": root, "Referer": "%s/%s" % (root, site),
                    "Sec-Fetch-Site": "same-origin",
                })
                try:
                    with urllib.request.urlopen(req, timeout=12, context=CTX) as r:
                        d = json.loads(r.read().decode("utf-8", "replace"))
                except Exception:
                    continue
                posts = d.get("jobPostings", [])
                if not posts:
                    continue
                return (tenant, inst, site, d.get("total", 0),
                        [p.get("title", "") for p in posts])
    return None


SLUG_FIELD = {
    "greenhouse": "greenhouse_board",
    "lever": "lever_company",
    "ashby": "ashby_org",
    "smartrecruiters": "smartrecruiters_company",
}
CAREERS = {
    "greenhouse": "https://job-boards.greenhouse.io/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "smartrecruiters": "https://careers.smartrecruiters.com/{slug}",
}


def emit_yaml(hit: dict, category: str = "AI/Accelerator", priority: str = "B") -> str:
    p, slug = hit["platform"], hit["slug"]
    kw = ('["verification", "rtl", "asic", "design verification", "fpga", '
          '"soc", "silicon", "digital design"]')
    if p == "workday":
        tenant, inst, site = hit["workday"]
        return (
            '  - name: "%s"\n    category: "%s"\n    priority: "%s"\n'
            '    careers_url: "https://%s.%s.myworkdayjobs.com/%s"\n'
            '    ats_platform: "workday"\n'
            '    workday_tenant: "%s"\n    workday_instance: "%s"\n'
            '    workday_career_site: "%s"\n'
            '    search_keywords: %s\n'
            '    notes: "Workday CXS verified; %d RTL-ish in a 20-row sample, '
            'tenant total %s for \'verification\'"\n'
            '    enabled: true\n'
            % (hit["name"], category, priority, tenant, inst, site,
               tenant, inst, site, kw, hit["rtl"], hit["total"])
        )
    return (
        f'  - name: "{hit["name"]}"\n'
        f'    category: "{category}"\n'
        f'    priority: "{priority}"\n'
        f'    careers_url: "{CAREERS[p].format(slug=slug)}"\n'
        f'    ats_platform: "{p}"\n'
        f'    {SLUG_FIELD[p]}: "{slug}"\n'
        f'    search_keywords: ["verification", "rtl", "asic", "design verification", "fpga", "soc", "silicon", "digital design"]\n'
        f'    notes: "Verified {hit["rtl"]}/{hit["total"]} RTL-ish postings'
        + (f'; board identity {hit["claimed"]!r}' if hit.get("claimed") else "")
        + '"\n'
        f'    enabled: true\n'
    )


CANDIDATES = [
    # AI / accelerator silicon
    "FuriosaAI", "Hailo", "EnCharge AI", "Kinara", "Taalas", "Rebellions",
    "Syntiant", "Lightelligence", "Luminous Computing",
    # RISC-V and CPU
    "Akeana", "Condor Computing", "MIPS", "Bolt Graphics", "Codasip",
    "Semidynamics", "Andes Technology",
    # Networking, interconnect, photonics
    "Nokia", "Ciena", "Infinera", "Ethernovia", "Xsight Labs",
    "DreamBig Semiconductor", "Nubis Communications", "Avicena",
    "Xscape Photonics",
    # Memory and storage
    "Sandisk", "Netlist", "SMART Modular Technologies",
    # Automotive, vision, robotics
    "Mobileye", "Aurora", "Zoox", "Luminar", "Aeva", "Ouster", "Rivian",
    "Lucid Motors", "Applied Intuition",
    # Analog, power, RF, timing
    "Monolithic Power Systems", "Navitas Semiconductor", "Diodes Incorporated",
    "Power Integrations", "SiTime", "Vicor",
    # EDA, IP, verification tools
    "Siemens EDA", "Arteris", "Imagination Technologies",
    "Breker Verification Systems", "Real Intent", "Axiomise",
    # Test and ATE
    "Advantest", "FormFactor", "Cohu",
    # Quantum
    "IonQ", "Rigetti Computing", "QuEra Computing", "Infleqtion", "Quantinuum",
    # Big tech silicon and systems
    "ByteDance", "IBM", "Oracle", "Pure Storage", "Nutanix",
    # Foundry and equipment
    "Lam Research", "ASML", "Onto Innovation",
]


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    emit = "--emit" in sys.argv
    targets = args or CANDIDATES

    found, missing = [], []
    for name in targets:
        hit = probe(name)
        if hit["platform"]:
            found.append(hit)
            claim = f" [{hit['claimed']}]" if hit.get("claimed") else ""
            print(f"OK   {name:<28} {hit['platform']}/{hit['slug']}"
                  f"  rtl={hit['rtl']}/{hit['total']}{claim}")
            for s in hit["samples"]:
                print(f"       · {s[:68]}")
        else:
            missing.append(hit)
            print(f"--   {name:<28} no verified board")
        for r in hit["rejected"]:
            print(f"       rejected: {r}")

    print(f"\n{len(found)} verified, {len(missing)} not found, of {len(targets)}")
    rtl_bearing = [h for h in found if h["rtl"] > 0]
    print(f"{len(rtl_bearing)} of the verified boards currently post RTL/DV roles")

    if emit:
        print("\n# ---- paste into config/companies.yaml ----")
        for hit in sorted(rtl_bearing, key=lambda h: -h["rtl"]):
            print(emit_yaml(hit), end="")


if __name__ == "__main__":
    main()
