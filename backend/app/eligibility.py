"""Eligibility / export-control risk detection and H1B sponsorship signal.

- ``detect_eligibility_risk`` scans a job description for citizenship,
  clearance, and export-control language and returns a risk level + the
  human-readable categories that matched.
- ``sponsors_h1b`` returns a company-level H1B sponsorship signal so
  international candidates can prioritize. (Phase 4 will replace the curated
  list with live DOL LCA disclosure data.)
"""

from __future__ import annotations

import re
from typing import Optional

# label -> regex patterns
_HIGH: dict[str, list[str]] = {
    "U.S. citizenship required": [
        r"u\.?\s?s\.?\s?citizen", r"must be a u\.?\s?s\.?\s?citizen",
        r"us citizenship", r"sole u\.?s\.? citizen",
    ],
    "Security clearance required": [
        r"security clearance", r"secret clearance", r"top secret", r"ts/sci",
        r"\bsci\b clearance", r"active clearance", r"polygraph", r"dod clearance",
    ],
}

_MEDIUM: dict[str, list[str]] = {
    "U.S. person / green card": [
        r"u\.?\s?s\.?\s?person", r"green card", r"permanent resident",
        r"lawful permanent resident",
    ],
    "ITAR / export control": [
        r"\bitar\b", r"export[-\s]control", r"\bear\b\s", r"controlled technology",
        r"export administration regulations",
    ],
    "Government / defense work": [
        r"government contract", r"cleared facility", r"defense contract",
    ],
    # Utilities and EPC firms state this in the posting far more often than
    # semiconductor employers do, and it rules an H1B candidate out as firmly as a
    # citizenship demand.
    "No visa sponsorship": [
        r"(will|do|does|can|could) not (provide |offer )?(visa )?sponsor",
        r"(unable|not able) to (provide |offer )?(employment )?(visa )?sponsor",
        r"without (the need for )?(current or future |future )?(visa )?sponsorship",
        r"sponsorship (is|will) not (be )?(available|provided|offered)",
        r"not eligible for (visa )?sponsorship",
        r"\bno (visa )?sponsorship",
    ],
}


def detect_eligibility_risk(text: str) -> tuple[str, list[str]]:
    """Return (risk_level, matched_labels). risk_level ∈ {low, medium, high}."""
    t = (text or "").lower()
    if not t:
        return "low", []

    high = [label for label, pats in _HIGH.items() if any(re.search(p, t) for p in pats)]
    if high:
        return "high", high

    medium = [label for label, pats in _MEDIUM.items() if any(re.search(p, t) for p in pats)]
    if medium:
        return "medium", medium

    return "low", []


# ── H1B sponsorship signal ────────────────────────────────────────────────────
#
# Two bugs lived here. First, this signal is a model @property and was never
# added to snapshot.LIST_FIELDS, so it never reached the corpus — and the app is
# now served from that corpus, so the frontend read `j.sponsors_h1b === false` on
# a field that was always undefined and the H1B filter silently matched EVERY
# job. Second, the lookup was exact set membership on a lowercased name, so
# "cadence" never matched the catalog's "Cadence Design Systems" and "renesas"
# never matched "Renesas Electronics" — both reported unknown. 22 of 54
# producing companies (101 US jobs) fell through that way.
#
# The company signal is a PRIOR, not an answer: it says whether this employer
# files H1B LCAs for engineering roles at all. The posting's own text is
# authoritative and overrides it — see h1b_accessible(). An employer that
# sponsors broadly still posts individual reqs gated on citizenship.
#
# This list is curated and reasoned, not scraped from a filing database. The
# upgrade path is the DOL's public LCA disclosure data, which is free but a few
# hundred MB per quarter; until that is wired in, "unknown" stays visibly
# unknown rather than being quietly treated as a yes.

# Corporate suffixes and category words that differ between how a company names
# itself and how a careers page writes it. Stripped from BOTH sides.
_NOISE = (
    "incorporated", "technologies", "technology", "semiconductors",
    "semiconductor", "design systems", "electronics", "solutions", "systems",
    "microsystems", "corporation", "company", "group", "labs", "inc", "corp",
    "llc", "ltd", "plc", "co", "sa", "nv", "ag",
)


def _norm(name: str) -> str:
    """Comparable form of a company name.

    Both the lookup keys and the query go through this, so "Cadence Design
    Systems", "Cadence" and "cadence design systems, inc." all land on one
    string. The lists below keep the readable full names.
    """
    t = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    for word in _NOISE:
        t = re.sub(r"\b" + re.escape(word) + r"\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Employers whose electrical engineering work is overwhelmingly on cleared,
# ITAR-controlled or federal programmes. Some of them file H1B petitions for
# other functions, but an H1B candidate cannot take these engineering roles.
# Marked False deliberately: a false "maybe" costs a candidate an application.
_NON_SPONSOR_NAMES = (
    "Lockheed Martin", "Northrop Grumman", "General Dynamics", "BAE Systems", "RTX",
    "Raytheon", "Collins Aerospace", "L3Harris", "Anduril", "SpaceX", "Blue Origin",
    "Rocket Lab", "Boeing", "Sierra Nevada Corporation", "Leidos", "SAIC",
    "Mercury Systems", "Curtiss-Wright", "Textron", "Moog",
    # Federal employers: US citizenship is a statutory requirement.
    "Tennessee Valley Authority", "Bonneville Power Administration",
    "Western Area Power Administration",
)

# Employers that routinely file H1B LCAs for engineering roles, grouped by why
# they qualify so a future reader can judge an addition. Posting text still
# overrides this (see h1b_accessible): a sponsor's req that says "no
# sponsorship" or demands citizenship is closed regardless.
_SPONSOR_NAMES = (
    # Grid & power OEMs — global engineering employers with large US sites.
    "GE Vernova", "Hitachi Energy", "Siemens Energy", "Siemens", "ABB",
    "Schneider Electric", "Eaton", "Hubbell", "Mitsubishi Electric Power Products",
    "Itron", "Landis+Gyr", "Vertiv", "Cummins", "Caterpillar", "nVent", "Danfoss",
    "Toshiba International", "WEG", "Generac", "Southwire",
    # Industrial automation.
    "Rockwell Automation", "Emerson", "Honeywell", "Parker Hannifin", "Regal Rexnord",
    "Yokogawa", "Endress+Hauser", "Mitsubishi Electric Automation",
    # Engineering consultancies & EPC firms — long-standing filers for power and
    # MEP engineers.
    "Burns & McDonnell", "Black & Veatch", "Sargent & Lundy", "WSP", "HDR", "Jacobs",
    "AECOM", "Stantec", "Mott MacDonald", "Bechtel", "Fluor", "Worley",
    "Kimley-Horn", "Ulteig", "TRC Companies", "Salas O'Brien", "Syska Hennessy",
    "Henderson Engineers", "IMEG", "Affiliated Engineers", "Dewberry",
    # Grid operators — hire power-systems engineers out of US graduate programmes.
    "ERCOT", "PJM Interconnection", "MISO", "California ISO", "NYISO",
    "ISO New England", "Southwest Power Pool",
    # Utilities that file LCAs for engineering roles.
    "Pacific Gas and Electric", "Southern California Edison", "Con Edison",
    "Duke Energy", "Exelon", "Dominion Energy", "Southern Company",
    "American Electric Power", "Xcel Energy", "NextEra Energy",
    # Renewables & storage.
    "Fluence", "Enphase Energy", "SolarEdge", "First Solar", "Nextracker",
    "Invenergy", "Ørsted", "RWE Clean Energy", "EDF power solutions",
    "Enel North America", "Form Energy", "Wärtsilä Energy Storage",
    # Data centers & cloud infrastructure.
    "Amazon", "Equinix", "Digital Realty", "CoreWeave", "Crusoe",
    # Automotive & EV.
    "Tesla", "Rivian", "Lucid Motors", "General Motors", "Ford Motor Company",
    "Stellantis", "Toyota North America", "Aptiv", "BorgWarner", "ChargePoint",
    "Zoox", "Waymo",
    # Rail.
    "Wabtec", "Siemens Mobility", "Alstom", "Hitachi Rail", "HNTB",
    # RF & communications.
    "Qualcomm", "Qorvo", "Skyworks Solutions", "Keysight Technologies", "Ericsson",
    "Nokia", "Verizon", "AT&T", "T-Mobile", "Motorola Solutions", "Garmin", "Ciena",
    "CommScope", "Rohde & Schwarz USA", "Viasat",
    # Electronics & semiconductors (applications / systems / power roles).
    "Texas Instruments", "Analog Devices", "Infineon Technologies", "Vicor",
    "Advanced Energy", "TE Connectivity", "Littelfuse",
    # Aerospace with substantial non-ITAR electrification work.
    "GE Aerospace", "Joby Aviation", "Archer Aviation",
)

# Reviewed, but the evidence for engineering sponsorship is not strong either
# way. Listed so the catalog test can tell "decided: unknown" from "forgot".
# These stay out of the strict H1B view until someone verifies them.
_UNVERIFIED_NAMES = (
    "Constellation Energy", "Entergy", "FirstEnergy", "PPL Corporation",
    "Eversource Energy", "National Grid", "CenterPoint Energy", "Ameren", "Evergy",
    "Alliant Energy", "WEC Energy Group", "DTE Energy", "Consumers Energy",
    "San Diego Gas & Electric", "Oncor", "PSEG", "Avangrid", "NiSource",
    "Arizona Public Service", "Portland General Electric", "Puget Sound Energy",
    "Idaho Power", "Berkshire Hathaway Energy", "OG&E", "Duquesne Light",
    "Salt River Project", "Vistra", "NRG Energy", "American Transmission Company",
    "ITC Holdings", "Schweitzer Engineering Laboratories", "S&C Electric",
    "Powell Industries", "Prolec GE", "Kiewit", "Mortenson", "Quanta Services",
    "MasTec", "Primoris", "Pattern Energy", "Apex Clean Energy", "Intersect Power",
    "Array Technologies", "Clearway Energy", "Ameresco", "Silicon Ranch",
    "Lightsource bp", "Vantage Data Centers", "QTS Data Centers",
    "Aligned Data Centers", "CyrusOne", "Stack Infrastructure", "Compass Datacenters",
    "EdgeConneX", "Switch", "Rosendin", "STV", "Amtrak", "Crown Castle",
)

_NON_SPONSOR = {_norm(n) for n in _NON_SPONSOR_NAMES}
_KNOWN_SPONSOR = {_norm(n) for n in _SPONSOR_NAMES}
_UNVERIFIED = {_norm(n) for n in _UNVERIFIED_NAMES}


def is_classified(company: str) -> bool:
    """Has someone made a sponsorship decision (including 'unverified')?"""
    c = _norm(company)
    return c in _NON_SPONSOR or c in _KNOWN_SPONSOR or c in _UNVERIFIED

# Eligibility levels that block an H1B candidate whatever the employer. "medium"
# covers green-card / US-person wording and ITAR, each of which rules an H1B
# holder out as firmly as an explicit citizenship demand.
_H1B_BLOCKING_RISK = frozenset({"high", "medium"})


def sponsors_h1b(company: str) -> Optional[bool]:
    """True = known H1B sponsor, False = typically US-person-only, None = unknown."""
    c = _norm(company)
    if not c:
        return None
    if c in _NON_SPONSOR:
        return False
    if c in _KNOWN_SPONSOR:
        return True
    return None


def h1b_accessible(company: str, eligibility_risk: str | None) -> bool:
    """Can an H1B candidate actually apply to this specific posting?

    Strict by design: the requirement is that the H1B filter show only jobs and
    companies that sponsor. So an unknown employer is NOT a yes, and a known
    sponsor's posting still fails when its own text demands citizenship, a green
    card, or ITAR-controlled access.
    """
    if sponsors_h1b(company) is not True:
        return False
    return (eligibility_risk or "low").lower() not in _H1B_BLOCKING_RISK
