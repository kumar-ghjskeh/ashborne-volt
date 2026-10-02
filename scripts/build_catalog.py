"""Build config/companies.yaml from the candidate list + verified connections.

One-time bootstrap (and re-runnable while the catalog is young): every employer
in config/candidates.tsv becomes a directory entry; those with a verified board
in config/connections.tsv are enabled with their adapter keys. After that,
companies.yaml is the source of truth and is edited by hand.

connections.tsv columns:  name  ats  spec  [engine]  [extra JSON object]
    workday  tenant.wdN/Site       greenhouse  board       lever  company
    ashby    org                   jibe        host        icims  host
    eightfold tenant/domain
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_tsv(path: Path) -> list[list[str]]:
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip() and not ln.startswith("#"):
            rows.append([c.strip() for c in ln.split("\t")])
    return rows


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def adapter_keys(ats: str, spec: str) -> list[tuple[str, str]]:
    if ats == "workday":
        host, site = spec.split("/", 1)
        tenant, inst = host.split(".")[:2]
        return [("workday_tenant", tenant), ("workday_instance", inst), ("workday_career_site", site)]
    if ats == "greenhouse":
        return [("greenhouse_board", spec)]
    if ats == "lever":
        return [("lever_company", spec)]
    if ats == "ashby":
        return [("ashby_org", spec)]
    if ats == "jibe":
        return [("jibe_host", spec)]
    if ats == "icims":
        return [("icims_host", spec)]
    if ats == "eightfold":
        tenant, domain = spec.split("/", 1)
        return [("eightfold_tenant", tenant), ("eightfold_domain", domain)]
    if ats == "successfactors":
        return [("successfactors_host", spec)]
    if ats == "smartrecruiters":
        return [("smartrecruiters_company", spec)]
    if ats == "amazon":
        return []
    raise ValueError(f"unknown ats {ats}")


def main() -> None:
    cands = read_tsv(ROOT / "config" / "candidates.tsv")
    conns = {r[0]: r for r in read_tsv(ROOT / "config" / "connections.tsv")}
    header = (ROOT / "config" / "companies.yaml").read_text(encoding="utf-8").split("companies:")[0]
    out = [header.rstrip() + "\n", "companies:\n"]
    sectors: dict[str, list[str]] = {}
    for name, sector, category, hq, priority, url in (r[:6] for r in cands):
        lines = [f"  - name: {q(name)}",
                 f"    sector: {q(sector)}",
                 f"    category: {q(category)}",
                 f"    hq: {q(hq)}",
                 f"    priority: {q(priority)}",
                 f"    careers_url: {q(url)}"]
        if name in conns:
            c = conns[name]
            ats, spec = c[1], c[2]
            engine = c[3] if len(c) > 3 else ""
            extra = json.loads(c[4]) if len(c) > 4 and c[4] else {}
            lines.append(f"    ats_platform: {q(ats)}")
            for k, v in adapter_keys(ats, spec):
                lines.append(f"    {k}: {q(v)}")
            if engine:
                lines.append(f"    engine: {q(engine)}")
            for k, v in extra.items():
                lines.append(f"    {k}: {json.dumps(v, ensure_ascii=False)}")
            lines.append("    enabled: true")
        else:
            lines += ["    ats_platform: \"generic\"", "    enabled: false"]
        sectors.setdefault(sector, []).append("\n".join(lines))
    for sector in sorted(sectors):
        out.append(f"\n  # ── {sector} " + "─" * max(0, 66 - len(sector)) + "\n")
        out.append("\n\n".join(sectors[sector]) + "\n")
    missing = [n for n in conns if n not in {r[0] for r in cands}]
    if missing:
        sys.exit(f"connections without a candidate row: {missing}")
    (ROOT / "config" / "companies.yaml").write_text("".join(out), encoding="utf-8")
    print(f"wrote {len(cands)} companies, {len(conns)} connected")


if __name__ == "__main__":
    main()
