"""Match scoring, job classification, and experience-level detection.

The domain knowledge (what counts as an EE job and which category it belongs to)
lives in :mod:`app.taxonomy`. This module turns a taxonomy verdict into the
scores, flags and labels the scrape engine stores and the UI shows.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from . import taxonomy as tx
from .models import ExperienceLevel, RemoteStatus


# ── Score labels ──────────────────────────────────────────────────────────────

def score_to_label(score: int) -> str:
    if score >= 85:
        return "Excellent Fit"
    if score >= 75:
        return "Strong Fit"
    if score >= 65:
        return "Good Fit"
    if score >= 50:
        return "Possible Fit"
    return "Low Fit"


# ── Relevance ─────────────────────────────────────────────────────────────────

def is_ee_relevant(title: str, description: str = "") -> tuple[bool, str]:
    """Is this posting an electrical-engineering job? Returns (relevant, reason).

    Title-first, so it works on list endpoints that return no description.
    """
    v = tx.classify(title, description)
    return v.relevant, v.reason


def relevance_verdict(title: str, description: str = "") -> tx.Verdict:
    """The full verdict, including whether a description could change it."""
    return tx.classify(title, description)


def is_software_only(title: str, description: str = "") -> bool:
    """True if the title is a software role with no controls/power signal."""
    return tx.classify(title, description).reason == "Software role"


def is_hardware_software_codesign(title: str, description: str = "") -> bool:
    """Kept for the model column; co-design is not a Volt concept."""
    return False


# ── Role flags (stored JSON) ──────────────────────────────────────────────────

def classify_role_flags(title: str, description: str = "") -> dict[str, bool]:
    """Which categories a posting touches — the title's own category plus any the
    description names strongly. Shown as secondary chips in the detail panel."""
    v = tx.classify(title, description)
    d = f" {(description or '').lower()} "
    flags = {f"is_{_slug(cat)}": False for cat in tx.CATEGORIES}
    if v.relevant and v.category in tx.CATEGORIES:
        flags[f"is_{_slug(v.category)}"] = True
    for cat, terms in tx.DESCRIPTION_CATEGORY_TERMS.items():
        if len(tx.term_hits(d, terms)) >= tx.DESCRIPTION_CATEGORY_MIN_HITS + 1:
            flags[f"is_{_slug(cat)}"] = True
    flags["is_software_only"] = v.reason == "Software role"
    flags["is_hardware_software_codesign"] = False
    return flags


def _slug(cat: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", cat.lower()).strip("_")


def role_flags_to_json(flags: dict[str, bool]) -> str:
    return json.dumps(flags)


# ── Main scoring function ─────────────────────────────────────────────────────

_SENIOR_TITLE_WORDS = (
    "senior", " sr ", " sr.", " staff ", "principal", "director", "architect",
    "manager", " vp ", "lead ", "distinguished", "engineer iii", "engineer iv",
)

_ENTRY_PHRASES = (
    "new grad", "new-grad", "entry level", "entry-level", "early career",
    "0-1 year", "0-2 year", "0-3 year", "0 to 1", "0 to 2", "0 to 3",
    "university grad", "recent graduate", "graduate engineer", "junior engineer",
    "associate engineer", "engineer in training", "engineer-in-training", "rotational program",
)


def calculate_match_score(
    job_title: str,
    description: str,
    company_priority: str,
    location: str,
    is_usa: bool = False,
    first_seen_recently: bool = False,
    ats_platform: str = "",
) -> tuple[int, list[str], dict[str, int]]:
    """Return (score 0-100, matched keywords list, breakdown dict).

    Role relevance only. USA is a hard gate elsewhere and is never scored.
    """
    score = 0
    matched: list[str] = []
    breakdown: dict[str, int] = {}

    title_l = job_title.lower()
    desc_l = description.lower()
    combined = title_l + " " + desc_l

    def add(reason: str, pts: int, kw: Optional[str] = None) -> None:
        nonlocal score
        score += pts
        breakdown[reason] = breakdown.get(reason, 0) + pts
        if kw and kw not in matched:
            matched.append(kw)

    v = tx.classify(job_title, description)
    if not v.relevant:
        add("Not an EE engineering role", -40)
        return 0, matched, breakdown

    # +35  the title alone decided the category (the strongest signal we have)
    title_cat = tx.title_category(job_title)
    if title_cat and title_cat == v.category and not v.needs_description:
        add(f"{v.category} title", 35, v.category)
    elif v.relevant:
        add("Electrical engineering title", 25, "electrical")

    # +20  real EE content in the description (not boilerplate)
    ee_hits = tx.term_hits(desc_l, tx.EE_DESCRIPTION_TERMS)
    if len(ee_hits) >= tx.EE_DESCRIPTION_MIN_HITS:
        add("EE methods & tools in description", 20)
        for t in ee_hits[:6]:
            if t not in matched:
                matched.append(t)
    elif ee_hits:
        add("Some EE terms in description", 10)

    # +20  explicit entry-level / EIT signal
    if any(p in combined for p in _ENTRY_PHRASES) or re.search(r"\bengineer\s+(i|1)\b", combined) \
            or re.search(r"\beit\b", combined):
        add("Entry-level / EIT signal", 20, "entry-level")

    # +10  high-priority company
    if company_priority in ("S", "A"):
        add("S/A-tier employer", 10, f"priority-{company_priority}")

    # +10  recent posting
    if first_seen_recently:
        add("Posted recently (< 24h)", 10, "recent")

    # +5  transparent ATS (reliable apply link)
    if ats_platform in ("greenhouse", "lever", "ashby", "workday"):
        add("Reliable apply link", 5)

    # −35  seniority in title
    if any(w in f" {title_l} " for w in _SENIOR_TITLE_WORDS):
        add("Senior/Staff/Principal in title", -35)

    # −30  requires 5+ years
    if re.search(r"\b([5-9]|\d{2,})\+?\s*years?\s*(of\s+)?(\w+\s+){0,3}experience", combined):
        add("Requires 5+ years experience", -30)

    return max(0, min(100, score)), matched, breakdown


def score_breakdown_json(breakdown: dict[str, int]) -> str:
    return json.dumps(breakdown)


# ── Classification helpers ─────────────────────────────────────────────────────

def detect_role_category(title: str, description: str = "") -> str:
    """The posting's EE category, or OUT_OF_SCOPE / OTHER when it has none."""
    v = tx.classify(title, description)
    if v.reason == "Software role":
        return "Software / Compiler"
    if not v.relevant:
        return tx.OUT_OF_SCOPE
    return v.category


def detect_experience_level(title: str, description: str = "") -> str:
    combined = (title + " " + description).lower()

    if tx.INTERN_TITLE.search(title):
        return ExperienceLevel.unknown
    if any(kw in combined for kw in (
        "new grad", "new-grad", "university grad", "recent graduate",
        "graduate engineer", "university graduate", "rotational program",
    )):
        return ExperienceLevel.new_grad
    if any(kw in combined for kw in (
        "0-1 year", "0-2 year", "0-3 year", "0 to 1", "0 to 2", "0 to 3",
    )):
        return ExperienceLevel.zero_to_three
    if any(kw in combined for kw in (
        "entry level", "entry-level", "early career", "junior engineer",
        "associate engineer", "engineer in training", "engineer-in-training",
    )) or re.search(r"\b(engineer\s+[i1]|eit)\b", combined):
        return ExperienceLevel.entry_level
    if re.search(r"\b(senior|sr\b|principal|lead\b|director|architect|manager|distinguished)\b", combined) \
            or tx.SENIOR_GRADE_TITLE.search(title):
        return ExperienceLevel.senior
    if re.search(r"\b([4-9]|\d{2,})\+?\s*years?\b", combined):
        return ExperienceLevel.mid_level
    return ExperienceLevel.unknown


def classify_seniority(title: str, description: str = "") -> tuple[str, int]:
    """Granular seniority with a confidence score (0-100).

    Returns one of: Intern, New Grad, Entry Level, Junior, Associate, Mid-Level,
    Senior, Staff, Principal, Lead, Manager, Unknown. Title signals are high
    confidence, years-of-experience inference medium, a bare guess low.

    Utilities and EPC firms grade engineers I–IV and use EIT/PE as rank markers:
    I and EIT are entry, II is mid, III/IV are senior.
    """
    t = title.lower()
    c = (title + " " + description).lower()

    if tx.INTERN_TITLE.search(t):
        return "Intern", 95
    # Multi-grade requisitions ("Engineer I, II, III or Principal", "Distribution
    # Planning Engineer (Entry, Staff, Senior, or Principal)") hire at whichever
    # level the candidate qualifies for, so they are open to new graduates.
    # Utilities post most of their engineering openings this way; the senior word
    # at the end of the range must not hide them from the entry-level view.
    if tx.MULTI_GRADE_ENTRY.search(t):
        return "Entry Level", 85
    if re.search(r"\b(manager|director|head of|vice president|superintendent)\b", t) or re.search(r"\bvp\b", t):
        return "Manager", 95
    if re.search(r"\b(principal|distinguished|fellow|chief engineer)\b", t):
        return "Principal", 95
    if re.search(r"\bstaff\b", t):
        return "Staff", 94
    if re.search(r"\b(tech(nical)? lead|lead)\b", t):
        return "Lead", 88
    if re.search(r"\b(senior|sr\.?)\b", t):
        return "Senior", 92
    if tx.SENIOR_GRADE_TITLE.search(t):
        return "Senior", 86
    if re.search(r"\b(architect|consulting engineer|specialist engineer)\b", t):
        return "Senior", 84
    if re.search(r"\b(new\s+grad(uate)?|new\s+college\s+grad|recent\s+graduate|university\s+grad(uate)?|"
                 r"early\s+career|campus|rotational|development program|graduate engineer)\b", c):
        return "New Grad", 92
    if re.search(r"\b(engineer[\s-]in[\s-]training|eit)\b", t):
        return "Entry Level", 92
    if re.search(r"\bassociate\b", t):
        return "Associate", 84
    if re.search(r"\b(junior|jr\.?)\b", t):
        return "Junior", 86
    if re.search(r"\bentry[\s-]level\b", c):
        return "Entry Level", 86
    if re.search(r"\b(engineer|level)\s+(i|1)\b", t) or re.search(r"\b\w+\s+engineer\s+i\b", t):
        return "Entry Level", 82
    if tx.MID_TITLE.search(t):
        return "Mid-Level", 80

    ymin, _ = detect_years_required(c)
    if ymin is not None:
        if ymin >= 8:
            return "Principal", 68
        if ymin >= 5:
            return "Senior", 74
        if ymin >= 3:
            return "Mid-Level", 70
        if ymin <= 2:
            return "Entry Level", 66
    if re.search(r"\b0[\s-]?(to|-)[\s-]?[123]\b|\b0-[123]\s*year", c):
        return "Entry Level", 72
    if re.search(r"\b(graduate engineer|associate engineer|junior engineer|engineer in training)\b", c):
        return "Entry Level", 60
    return "Unknown", 30


_SENIOR_TIERS = ("Senior", "Staff", "Principal", "Lead", "Manager")
_ENTRY_TIERS = ("New Grad", "Entry Level")


def classify_seniority_flags(title: str, description: str = "") -> tuple[bool, bool]:
    """(is_entry_level, is_senior), from the same engine that sets the displayed
    level, so a card's level and the filters can never disagree."""
    level, _ = classify_seniority(title, description)
    return level in _ENTRY_TIERS, level in _SENIOR_TIERS


def is_candidate_friendly_job(
    job_title: str, description: str, company_priority: str, ats_platform: str
) -> bool:
    """Likely open to an early-career engineer even without an explicit signal:
    a clearly-categorised EE title, no seniority marker, no 4+ year demand, at a
    top-tier employer."""
    v = tx.classify(job_title, description)
    if not v.relevant or v.needs_description:
        return False
    if re.search(
        r"\b(senior|sr\b|principal|staff\b|lead\b|director|architect|manager|distinguished|"
        r"engineer\s+(iii|iv|3|4)|5\+|7\+|10\+)\b", job_title.lower(),
    ):
        return False
    if tx.INTERN_TITLE.search(job_title):
        return False
    ymin, _ = detect_years_required(description)
    if ymin is not None and ymin >= 4:
        return False
    return company_priority in ("S", "A")


def detect_years_required(text: str) -> tuple[Optional[int], Optional[int]]:
    range_match = re.search(r"(\d+)\s*[-–to]+\s*(\d+)\s*years?", text.lower())
    if range_match:
        return int(range_match.group(1)), int(range_match.group(2))
    plus_match = re.search(r"(\d+)\+\s*years?", text.lower())
    if plus_match:
        return int(plus_match.group(1)), None
    single = re.search(r"(\d+)\s*years?\s*(of\s+)?experience", text.lower())
    if single:
        n = int(single.group(1))
        return n, n
    return None, None


# ── Fit scores (job-intrinsic, resume-independent) ──────────────────────────
# A New Grad / entry candidate's realistic odds for a role, and (separately) how
# suited the role is to an experienced candidate. USA is NOT part of these — it
# is a hard gate elsewhere. These drive the card ring, default ranking, and the
# Fit Score Breakdown tab.

_NEW_GRAD_CAP = {
    "New Grad": 100, "Entry Level": 100,
    "Junior": 85, "Associate": 85,
    "Mid-Level": 70,
    "Senior": 55,
    "Lead": 45, "Staff": 45, "Principal": 45, "Manager": 45,
    # An internship is not a job a graduate can take, however junior.
    "Intern": 50,
    "Unknown": 72,
}

_SENIOR_TITLE_RE = re.compile(
    r"\b(staff|principal|lead|manager|director|distinguished|fellow|architect)\b", re.I)
_NEWGRAD_FRIENDLY_RE = re.compile(
    r"\b(new\s+grad|new\s+college\s+grad|entry[\s-]level|university\s+grad(uate)?|recent\s+graduate)\b", re.I)


def new_grad_fit_score(
    experience_level: str, is_senior: bool, is_entry_level: bool,
    is_candidate_friendly: bool, years_required_min: Optional[int],
    title: str = "", description: str = "",
) -> int:
    """How realistic this role is for a New Grad / entry-level candidate (0-100).
    Seniority, years required, and title level CAP the score so a Staff/Senior or
    4+ yr role can never read as an Excellent fit (per the scoring spec)."""
    cap = _NEW_GRAD_CAP.get(experience_level or "Unknown", 72)

    y = years_required_min
    if y is not None:
        if y >= 5:
            cap = min(cap, 50)
        elif y == 4:
            cap = min(cap, 60)
        elif y == 3:
            cap = min(cap, 70)
        elif y == 2:
            cap = min(cap, 82)
        elif y == 1:
            cap = min(cap, 90)

    multi_grade = bool(tx.MULTI_GRADE_ENTRY.search(title or ""))
    if is_senior:
        cap = min(cap, 55)
    # "Engineer I, II, III or Principal" names a senior grade but hires at entry.
    if _SENIOR_TITLE_RE.search(title or "") and not multi_grade:
        cap = min(cap, 45)

    # Rare exception: a role capped only by an INFERRED senior signal (years, or
    # an inferred level) that EXPLICITLY invites new grads can recover. It NEVER
    # applies when the TITLE itself carries a senior rank (Senior/Sr/Staff/
    # Principal/Lead/Manager/Director/Architect/…) — that is authoritative and
    # must not be overridden by description keyword bleed (e.g. a "Principal …
    # Engineer" whose JD happens to mention 'recent graduate').
    title_is_senior = bool(re.search(
        r"\b(senior|sr\.?|staff|principal|lead|manager|director|distinguished|fellow|architect)\b",
        title or "", re.I))
    if cap <= 55 and not title_is_senior and experience_level != "Intern" \
            and _NEWGRAD_FRIENDLY_RE.search(f"{title} {description}"):
        cap = max(cap, 75)

    score = cap
    # An unknown role with no entry signal shouldn't read as a strong fit.
    if (experience_level or "Unknown") == "Unknown" and y is None \
            and not is_entry_level and not is_candidate_friendly:
        score = min(cap, 66)
    return max(0, min(100, score))


_EXPERIENCED_FIT = {
    "Staff": 95, "Principal": 95, "Director": 95, "Fellow": 95,
    "Lead": 90, "Manager": 88, "Senior": 90, "Mid-Level": 80,
    "Associate": 62, "Junior": 60, "Entry Level": 45, "New Grad": 40, "Intern": 25,
    "Unknown": 70,
}


def experienced_fit_score(
    experience_level: str, is_senior: bool, years_required_min: Optional[int],
) -> int:
    """How suited the role is to an EXPERIENCED candidate (0-100). Senior/Staff
    roles score high here even when New Grad Fit is low."""
    base = _EXPERIENCED_FIT.get(experience_level or "Unknown", 70)
    y = years_required_min
    if y is not None:
        if y >= 5:
            base = max(base, 92)
        elif y >= 3:
            base = max(base, 82)
    if is_senior:
        base = max(base, 88)
    return max(0, min(100, base))


def new_grad_fit_label(score: int) -> str:
    """Short label for the card ring (only 'Excellent' at 90+)."""
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Strong Fit"
    if score >= 60:
        return "Stretch"
    if score >= 46:
        return "Weak Fit"
    return "Not Entry"


def overall_recommendation(new_grad_fit: int) -> str:
    """Full recommendation label for the detail-panel header."""
    if new_grad_fit >= 90:
        return "Excellent New Grad Fit"
    if new_grad_fit >= 75:
        return "Strong Entry-Level Fit"
    if new_grad_fit >= 60:
        return "Possible Junior Stretch"
    if new_grad_fit >= 46:
        return "Stretch Role"
    return "Not Entry-Level Fit"


def detect_remote_status(location: str, description: str = "") -> str:
    combined = (location + " " + description).lower()
    if "remote" in combined and "hybrid" not in combined:
        return RemoteStatus.remote
    if "hybrid" in combined:
        return RemoteStatus.hybrid
    if location.strip():
        return RemoteStatus.onsite
    return RemoteStatus.unknown


def normalize_title(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[-,|]\s*(remote|hybrid|onsite|new\s*grad|entry.level)\s*$", "", t)
    t = re.sub(r"\s*\((remote|hybrid|new\s*grad|entry.level)[^)]*\)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def build_relevance_reason(title: str, description: str, breakdown: dict[str, int]) -> str:
    """Build a human-readable relevance reason string."""
    pos = [k for k, v in breakdown.items() if v > 0]
    neg = [k for k, v in breakdown.items() if v < 0]
    parts = []
    if pos:
        parts.append("Matched: " + "; ".join(pos[:3]))
    if neg:
        parts.append("Penalties: " + "; ".join(neg[:2]))
    return ". ".join(parts)
