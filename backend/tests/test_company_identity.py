"""A configured board must belong to the company we think it does.

The Greenhouse board token `ventana` does not belong to Ventana Micro Systems —
it belongs to "Ventana by Buckner", a senior-living operator, and this repo
scraped it for months. `flex` is not Flex Logix but "Flex". `rain` is not Rain AI
but Rain the fintech. All three produced zero rows, so nothing looked wrong; the
only reason a nursing home's CNA and housekeeping postings never surfaced in a
semiconductor job board is that the keyword filter happened to reject every
nursing title. The filter was load-bearing for correctness it was never meant to
carry.

verify_sources.py already checked that each endpoint returns DATA. That is not
the same question as whether the data is OURS, which is why the drift survived.

These tests are offline and structural: they check the config can't express the
mistake silently. The live identity check is scripts/verify_sources.py --identity,
which runs weekly in CI and needs network.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

CFG = Path(__file__).resolve().parents[2] / "config" / "companies.yaml"

# Board tokens proven to belong to an unrelated company. Scraping any of these
# ingests a different employer's postings. Keep the reason attached — a bare
# blocklist invites someone to "fix" it by deleting the entry.
KNOWN_FOREIGN_BOARDS = {
    ("greenhouse", "ventana"): 'Greenhouse board name is "Ventana by Buckner" (senior living), not Ventana Micro Systems',
    ("greenhouse", "flex"): 'Greenhouse board name is "Flex", not Flex Logix',
    ("ashby", "rain"): "Ashby board is Rain the fintech, not Rain AI",
}

_SLUG_FIELDS = {
    "greenhouse": "greenhouse_board",
    "ashby": "ashby_org",
    "lever": "lever_company",
    "smartrecruiters": "smartrecruiters_company",
}


def _companies() -> list[dict]:
    with CFG.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["companies"]


def test_no_enabled_company_points_at_a_foreign_board():
    """The regression that let a nursing home into a semiconductor scraper."""
    offenders = []
    for c in _companies():
        if not c.get("enabled", True):
            continue  # disabled entries keep the bad token for documentation
        platform = (c.get("ats_platform") or "").lower()
        field = _SLUG_FIELDS.get(platform)
        if not field:
            continue
        slug = (c.get(field) or "").lower()
        reason = KNOWN_FOREIGN_BOARDS.get((platform, slug))
        if reason:
            offenders.append(f"{c['name']} -> {platform}/{slug}: {reason}")
    assert not offenders, (
        "These ENABLED companies point at a board belonging to someone else:\n  "
        + "\n  ".join(offenders)
        + "\nA wrong board is worse than no board: it silently ingests another "
        "employer's postings, and only the keyword filter stands in the way."
    )


def test_every_enabled_api_company_declares_its_slug():
    """A missing slug makes the adapter guess from careers_url — which is how a
    display-only URL ends up driving what we actually fetch."""
    missing = []
    for c in _companies():
        if not c.get("enabled", True):
            continue
        platform = (c.get("ats_platform") or "").lower()
        field = _SLUG_FIELDS.get(platform)
        if field and not c.get(field):
            missing.append(f"{c['name']} ({platform}) has no `{field}`")
    assert not missing, (
        "Enabled companies with no explicit board slug:\n  " + "\n  ".join(missing)
    )


def test_careers_url_and_scraper_slug_are_not_unrelated():
    """Kioxia's careers_url said KIOXIAAmerica (0 postings) while the scraper used
    kioxia (18). Only one of those is what we fetch, so a reader auditing the
    config by eye draws the wrong conclusion about what is being scraped.

    Deliberately NOT an equality check: a real slug can legitimately differ from
    the display path — Lever serves Mythic at `mythic-ai.com` while `mythic-ai`
     404s. What matters is that the two are recognisably the same organisation, so
    this flags only pairs sharing no meaningful prefix."""
    HOSTS = {
        "greenhouse": r"(?:job-boards|boards)\.greenhouse\.io/([A-Za-z0-9_-]+)",
        "ashby": r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)",
        "lever": r"jobs\.lever\.co/([A-Za-z0-9_-]+)",
        "smartrecruiters": r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)",
    }
    mismatched = []
    for c in _companies():
        if not c.get("enabled", True):
            continue
        platform = (c.get("ats_platform") or "").lower()
        field = _SLUG_FIELDS.get(platform)
        if not (field and platform in HOSTS):
            continue
        slug = c.get(field)
        m = re.search(HOSTS[platform], c.get("careers_url") or "")
        if not (slug and m):
            continue
        a, b = m.group(1).lower(), str(slug).lower()
        # Strip a trailing TLD so `mythic-ai.com` and `mythic-ai` compare equal.
        a, b = a.split(".")[0], b.split(".")[0]
        if not (a.startswith(b) or b.startswith(a)):
            mismatched.append(
                f"{c['name']}: careers_url says {m.group(1)!r} but {field} is {slug!r}"
            )
    assert not mismatched, (
        "careers_url disagrees with the slug actually scraped:\n  "
        + "\n  ".join(mismatched)
    )
