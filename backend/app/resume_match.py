"""Resume ↔ job matching, defensibility, safe tailoring, and interview prep.

All computed live from the stored resume profile so it always reflects the
current resume. Never suggests claiming a skill the resume/projects don't
support — suggestions are tiered Safe to Add / Reword Only / Learn First /
Do Not Add.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

from .resume_parser import (
    CONCEPTS, LANGUAGES, PROJECT_SIGNALS, PROTOCOLS, STANDARDS, STUDIES, TOOLS,
)
from .scoring import (
    experienced_fit_score, new_grad_fit_score, overall_recommendation,
)
from . import taxonomy as tx

_ALL = {**STANDARDS, **STUDIES, **TOOLS, **PROTOCOLS, **CONCEPTS, **LANGUAGES}
_TOOLSET = set(TOOLS) | set(PROTOCOLS)  # things you must actually have used

# Skill equivalences → "Reword Only" (the résumé already proves it under another name)
_EQUIVALENT: dict[str, list[str]] = {
    "Load Flow": ["PSS/E", "PowerWorld", "ETAP", "CYME", "Synergi Electric", "PSLF", "PowerFactory"],
    "Short Circuit Analysis": ["ETAP", "SKM PowerTools", "EasyPower", "Aspen OneLiner", "CAPE"],
    "Arc Flash Analysis": ["ETAP", "SKM PowerTools", "EasyPower"],
    "Protective Device Coordination": ["Relay Settings", "SKM PowerTools", "ETAP", "Aspen OneLiner"],
    "Relay Settings": ["SEL AcSELerator", "Protective Relaying", "Aspen OneLiner", "CAPE"],
    "Protective Relaying": ["Relay Settings", "SEL AcSELerator"],
    "PLC Programming": ["Studio 5000 / RSLogix", "TIA Portal / STEP 7", "CODESYS", "Ladder Logic", "Structured Text"],
    "HMI Development": ["FactoryTalk", "Ignition", "AVEVA / Wonderware"],
    "SCADA": ["Ignition", "AVEVA / Wonderware", "DNP3", "Modbus", "OSIsoft PI"],
    "Single-Line Diagrams": ["AutoCAD", "AutoCAD Electrical", "Schematics & Wiring Diagrams"],
    "Schematics & Wiring Diagrams": ["AutoCAD Electrical", "EPLAN", "Altium Designer", "OrCAD"],
    "Converter Design": ["PLECS", "LTspice", "PSIM", "DC-DC Converters", "Power Electronics"],
    "Power Electronics": ["Converter Design", "Inverters", "DC-DC Converters", "PLECS"],
    "PCB Layout": ["Altium Designer", "OrCAD", "KiCad", "Cadence Allegro"],
    "PCB Design": ["Altium Designer", "OrCAD", "KiCad", "PCB Layout"],
    "RF Design": ["ANSYS HFSS", "Keysight ADS", "CST Studio", "AWR Microwave Office", "Antennas"],
    "EM / FEA Simulation": ["ANSYS Maxwell", "ANSYS HFSS", "COMSOL", "CST Studio"],
    "Solar PV": ["PVsyst", "Helioscope"],
    "Lighting Calculations": ["AGi32 / DIALux", "Lighting Design"],
    "Load Calculations": ["NEC / NFPA 70", "Revit"],
}

# Which broad area each skill belongs to (for Safe-to-Add vs Learn-First).
_AREA: dict[str, str] = {}
for _s in STANDARDS: _AREA[_s] = "codes"
for _s in STUDIES: _AREA[_s] = "studies"
for _s in CONCEPTS: _AREA[_s] = "domain"
for _s in LANGUAGES: _AREA[_s] = "programming"
for _s in PROTOCOLS: _AREA[_s] = "tool"
for _s in TOOLS: _AREA[_s] = "tool"

_AREA_LABEL = {"codes": "codes & standards", "studies": "engineering-studies", "domain": "domain",
               "programming": "programming", "tool": "tooling"}


@lru_cache(maxsize=8192)
def _extract_cached(t: str) -> tuple:
    return tuple(canon for canon, pats in _ALL.items() if any(re.search(p, t) for p in pats))


def extract_job_skills(job_text: str) -> list[str]:
    """Canonical skills/keywords found in the text. Cached (same posting text →
    same result) so the taxonomy regex runs once per distinct posting."""
    return list(_extract_cached((job_text or "").lower()))


def job_skills_for(job: dict) -> list[str]:
    """Prefer the precomputed `job_skills` stored on the posting (fast split);
    fall back to live extraction when it isn't populated yet."""
    stored = job.get("job_skills")
    if stored:
        return [s for s in stored.split(",") if s]
    return extract_job_skills(" ".join([
        job.get("job_title", ""), job.get("cleaned_description", "") or "",
        job.get("matched_keywords", "") or "",
    ]))


def _area_strength(profile: dict) -> dict[str, int]:
    return {
        "codes": len(profile.get("standards", [])),
        "studies": len(profile.get("studies", [])),
        "domain": len(profile.get("concepts", [])),
        "programming": len(profile.get("languages", [])),
        "tool": len(profile.get("tools", [])) + len(profile.get("protocols", [])),
    }


# Words in a project description that signal it backs a given skill area — used to
# point a "Safe to Add" suggestion at the candidate's concrete supporting project.
_AREA_PROJECT_HINTS = {
    "studies": ("study", "studies", "analysis", "load flow", "short circuit", "arc flash", "coordination",
                "design", "commissioning", "test", "simulation"),
    "domain": ("substation", "solar", "battery", "motor", "inverter", "converter", "grid", "plc",
               "antenna", "relay", "transformer", "microgrid", "pcb", "ev", "power"),
    "codes": ("nec", "ieee", "nfpa", "code", "standard", "compliance"),
    "programming": ("python", "matlab", "c++", "script", "labview", "automation"),
    "tool": (),
}


def _short_title(proj: str) -> str:
    # Bounded input: the profile comes from the caller, and the split pattern is
    # quadratic on long whitespace runs.
    proj = (proj or "")[:200]
    t = re.split(r"\s+[—:]|\s-\s|\(", proj, 1)[0].strip()
    return (t or proj)[:60].strip()


# Past-tense verbs that begin résumé BULLET lines (not project titles).
_BULLET_VERBS = frozenset((
    "built", "verified", "implemented", "ran", "created", "designed", "debugged",
    "developed", "added", "executed", "achieved", "reached", "used", "performed",
    "wrote", "configured", "integrated", "analyzed", "optimized", "reduced",
    "improved", "led", "collaborated", "architected", "validated", "simulated",
    "measured", "modeled", "prepared", "conducted", "commissioned", "programmed",
    "calculated", "sized", "installed", "tested", "troubleshot",
))


def _looks_like_title(s: str) -> bool:
    """A real project title is short, capitalised, and doesn't start like a
    bullet ("Designed …", "Built …")."""
    s = (s or "").strip()
    if not s or not s[0].isupper():
        return False
    words = s.split()
    if len(words) > 8:
        return False
    return words[0].lower().rstrip(".,") not in _BULLET_VERBS


def _evidence_project(skill: str, area: str, projects: list[str]) -> str:
    """A concrete project that supports this skill — first by direct mention, then
    by area. Returns a short project title, or "" if none."""
    sl = skill.lower()
    for p in projects:
        if sl in p.lower():
            return _short_title(p)
    for p in projects:
        pl = p.lower()
        if any(h in pl for h in _AREA_PROJECT_HINTS.get(area, ())):
            return _short_title(p)
    return ""


def _classify_suggestion(skill: str, profile: dict, strengths: dict[str, int]) -> tuple[str, str]:
    """Return (tier, rationale) for a missing skill. Never fabricate."""
    resume_skills = set(profile.get("all_skills", []))
    projects = profile.get("projects", []) or []
    for equiv in _EQUIVALENT.get(skill, []):
        if equiv in resume_skills:
            return "Reword Only", f"Your résumé already shows {equiv} — reword it to surface “{skill}” explicitly."
    area = _AREA.get(skill, "tool")
    label = _AREA_LABEL.get(area, area)
    # Specific software, test equipment and protocols you've never used → never claim.
    if skill in _TOOLSET:
        if strengths.get("tool", 0) >= 3 or strengths.get("studies", 0) >= 3:
            return "Learn First", f"Adjacent to your background, but learn {skill} hands-on before claiming it."
        return "Do Not Add", f"No supporting experience with {skill} — leave it off to avoid an ATS/interview flag."
    if strengths.get(area, 0) >= 3:
        ev = _evidence_project(skill, area, projects)
        if ev:
            return "Safe to Add", f"Your “{ev}” project already demonstrates this {label} work — safe to state {skill} explicitly."
        return "Safe to Add", f"Well-supported by your {label} experience — safe to make explicit."
    if strengths.get(area, 0) >= 1:
        return "Learn First", f"Some {label} foundation, but strengthen {skill} before featuring it."
    return "Do Not Add", f"No supporting background for {skill} yet."


def _recommended_resume(role_category: str, profile: dict) -> str:
    rc = role_category or ""
    if rc in tx.CATEGORIES:
        return f"{rc} Résumé"
    focus = profile.get("role_focus") or ""
    if focus in tx.CATEGORIES:
        return f"{focus} Résumé"
    return "General Electrical Engineering Résumé"


_INTERVIEW_TOPICS: dict[str, list[str]] = {
    tx.POWER: ["Per-unit system and three-phase fundamentals", "Symmetrical components & fault types",
               "Load flow concepts (PV/PQ/slack buses)", "Protective relaying: overcurrent, distance, differential",
               "Transformer connections & grounding", "Breaker-and-a-half vs ring bus layouts",
               "NERC reliability standards you've touched", "Reading a one-line / three-line diagram"],
    tx.ENERGY: ["PV array sizing (strings, DC/AC ratio, irradiance)", "Inverter types and grid codes (IEEE 1547)",
                "BESS sizing: power vs energy, C-rate, degradation", "Interconnection process & studies",
                "Collector system and substation design", "Capacity factor and energy yield (PVsyst)",
                "Microgrid islanding & grid-forming control"],
    tx.INDUSTRIAL: ["Motor starting methods & VFDs", "MCCs, switchgear and power distribution in a plant",
                    "Reliability & root-cause analysis (5-Whys, FMEA)", "Preventive vs predictive maintenance",
                    "Arc-flash labelling & NFPA 70E", "Managing a capital project / outage scope"],
    tx.CONTROLS: ["PLC scan cycle, ladder logic and structured text", "PID loops: tuning and stability",
                  "HMI/SCADA architecture", "Industrial networks (EtherNet/IP, Profinet, Modbus)",
                  "Safety systems: interlocks, SIL, E-stop circuits", "Commissioning & FAT/SAT"],
    tx.INSTRUMENTATION: ["4–20 mA loops and HART", "Flow/pressure/level/temperature measurement",
                         "Reading P&IDs and loop diagrams (ISA-5.1)", "Calibration & accuracy",
                         "Control valves and sizing", "Safety instrumented systems (IEC 61511)"],
    tx.DESIGN: ["Circuit analysis fundamentals (KVL/KCL, Thevenin)", "Conductor & breaker sizing to NEC",
                "Voltage drop and short-circuit ratings", "Schematic capture & PCB design flow",
                "Grounding and bonding", "Design reviews and drawing standards"],
    tx.MACHINES: ["Induction vs synchronous machines", "Torque–speed curves and motor starting",
                  "Equivalent circuits and losses", "Winding design and insulation classes",
                  "Thermal limits and cooling", "Generator excitation and protection"],
    tx.POWER_ELECTRONICS: ["Buck/boost/flyback/LLC topologies", "Switching losses and thermal design",
                           "Magnetics design (inductors, transformers)", "Control loops & compensation",
                           "Gate drive and SiC/GaN considerations", "EMI filtering and layout"],
    tx.RF: ["S-parameters and impedance matching (Smith chart)", "Link budgets and noise figure",
            "Antenna fundamentals (gain, pattern, VSWR)", "Mixers, LNAs, PAs and linearity",
            "Transmission lines and microstrip", "RF test: VNA, spectrum analyzer"],
    tx.EMC: ["Radiated vs conducted emissions", "Grounding, shielding and filtering",
             "PCB layout for EMC (return paths, stack-up)", "Standards: CISPR, FCC Part 15, MIL-STD-461",
             "Pre-compliance testing & debug", "ESD and immunity"],
    tx.INFRASTRUCTURE: ["Load calculations and service sizing (NEC Art. 220)", "Power distribution for buildings",
                        "Emergency/standby power (generators, ATS, UPS)", "Lighting design & controls",
                        "Data-center redundancy (N+1, 2N) and tier levels", "Coordination with MEP trades & Revit"],
    tx.TRANSPORT: ["Aircraft/vehicle electrical power systems", "Wire harness design & EWIS",
                   "DO-160 / MIL-STD-704 environmental and power quality", "Traction power & OCS basics",
                   "High-voltage battery systems & safety", "Systems engineering & requirements"],
}
_GENERIC_TOPICS = _INTERVIEW_TOPICS[tx.DESIGN]


# Per-employer interview emphasis. Generic fallback for everyone else.
_COMPANY_FOCUS = {
    "ge vernova": "Grid & generation OEM — expect power-systems fundamentals, equipment knowledge and project examples.",
    "siemens": "Broad electrification OEM — fundamentals plus product/application depth for the specific business unit.",
    "siemens energy": "Grid/HVDC/generation — power-systems fundamentals, HV equipment and project execution.",
    "hitachi energy": "HV equipment & HVDC — transformer/switchgear fundamentals and grid applications.",
    "schweitzer engineering laboratories": "Protection & automation — relaying theory, SEL relay logic and fault analysis are central.",
    "burns & mcdonnell": "EPC design — NEC/IEEE application, studies (short circuit, arc flash), and client-facing project work.",
    "black & veatch": "EPC design — substation/transmission design standards and multidisciplinary coordination.",
    "duke energy": "Utility — behavioral panel (STAR) plus T&D fundamentals, safety culture and reliability.",
    "tesla": "Hardware ownership end-to-end — fast design iteration, first-principles fundamentals and test.",
    "schneider electric": "Power distribution & automation products — application engineering and fundamentals.",
    "eaton": "Power management — distribution equipment, power quality and application engineering.",
    "rockwell automation": "Industrial automation — PLC/drives fundamentals and customer applications.",
}


def _interview_rounds(tier: str, role_category: str) -> list[dict]:
    """Likely loop for an EE role. Utilities and EPC firms lean on behavioral
    panels and fundamentals; OEMs add a technical deep-dive or case study."""
    cat = role_category if role_category in _INTERVIEW_TOPICS else tx.DESIGN
    topics = ", ".join(t.split(" (")[0] for t in _INTERVIEW_TOPICS[cat][:3])
    recruiter = "15–30 min — background, work authorization, relocation, travel/on-call expectations, salary range."
    tech = f"Technical fundamentals for {cat}: {topics}."
    case = ("Case / design problem — e.g. size a feeder and its protection, walk through a one-line, "
            "or reason about a failure you'd troubleshoot. Talk through assumptions and codes.")
    deepdive = "Project deep-dive — your strongest design/study/capstone: what you decided, which standards applied, what you'd change."
    behavioral = "Behavioral panel (STAR) — safety, teamwork, handling a mistake, working with field crews or clients."
    license = "Career-path conversation — EIT/FE status, PE plans, and willingness to rotate or travel."

    if tier in ("S", "A"):
        return [
            {"name": "1 · Recruiter screen", "what": recruiter},
            {"name": "2 · Technical phone screen", "what": tech},
            {"name": "3 · Onsite — case / design problem", "what": case},
            {"name": "4 · Onsite — project deep-dive", "what": deepdive},
            {"name": "5 · Behavioral panel", "what": behavioral},
            {"name": "6 · Hiring manager", "what": license},
        ]
    if tier == "B":
        return [
            {"name": "1 · Recruiter screen", "what": recruiter},
            {"name": "2 · Technical interview", "what": tech + " " + case},
            {"name": "3 · Panel — project + behavioral", "what": deepdive + " " + behavioral},
        ]
    return [
        {"name": "1 · Recruiter / manager screen", "what": recruiter},
        {"name": "2 · Technical + team", "what": tech + " Expect a practical problem."},
        {"name": "3 · Behavioral", "what": behavioral},
    ]


def _interview_prep(role_category: str, job_skills: list[str], profile: dict,
                    tier: str = "", company: str = "") -> dict:
    base = _INTERVIEW_TOPICS.get(role_category, _GENERIC_TOPICS)
    # JD-specific standards and tools on top of the category baseline.
    extra = [s for s in job_skills if s in STANDARDS or s in TOOLS][:3]
    topics = base + [f"{p} — how you've applied it" for p in extra]
    defense = []
    for proj in profile.get("projects", [])[:4]:
        short = proj.split("—")[0].split(" - ")[0].strip()[:70]
        if short:
            defense.append(f"Walk through “{short}” — requirements, design choices, codes applied, and results.")
    for sig in (profile.get("project_signals") or [])[:3]:
        defense.append(f"Be ready to defend your {sig} work in depth.")
    company_focus = _COMPANY_FOCUS.get((company or "").lower().strip(),
        f"Read {company}'s recent projects and service territory or product lines, and connect your work to them." if company else "")
    return {
        "rounds": _interview_rounds(tier, role_category),
        "company_focus": company_focus,
        "technical_topics": topics[:8],
        "resume_defense": defense[:6],
    }


_SENIOR_WORDS = ("senior", "sr.", "staff", "principal", "lead", "manager", "director", "fellow")


def _experience_fit(profile: dict, job: dict) -> int:
    """How realistic the role's seniority is for THIS candidate (0–100).

    Strict for a no-/low-experience resume: a *stated* years requirement the
    candidate doesn't meet, or a senior title, sharply lowers the fit — even if
    the posting is loosely tagged "entry level" (many "2+ yrs" roles are). A
    genuine new-grad role with no years bar scores 100."""
    yrs = profile.get("years_experience", 0) or 0
    level = (job.get("experience_level") or "").lower()
    title = (job.get("job_title") or "").lower()
    req_min = job.get("years_required_min")
    is_senior = job.get("is_senior") or any(w in level or w in title for w in _SENIOR_WORDS)
    entry_signal = job.get("is_entry_level") or any(
        k in level for k in ("new grad", "entry", "junior", "intern", "university", "graduate")
    )

    if yrs <= 1:  # new grad / no professional experience
        if is_senior:
            return 22  # senior / staff / principal — a real stretch
        # A concrete years requirement the candidate lacks dominates, even when
        # the posting is tagged entry-level — this is what a recruiter screens on.
        if req_min is not None and req_min >= 1:
            return {1: 78, 2: 55, 3: 40}.get(req_min, 26)
        if entry_signal:
            return 100  # genuine new-grad / entry role, no years bar
        if job.get("is_candidate_friendly") or "associate" in level or "mid" in level:
            return 70
        return 58  # level unknown, no stated requirement — plausible, unproven
    # experienced candidate
    if req_min is not None:
        if yrs >= req_min:
            return 95
        if yrs >= req_min - 2:
            return 75
        return 55
    if is_senior and yrs < 5:
        return 66
    return 78


def _domain_score(profile: dict, job: dict) -> int:
    """Role-category alignment with the résumé's focus (0–100)."""
    rc = job.get("role_category") or ""
    focus = profile.get("role_focus") or ""
    if not rc or rc in ("Unknown", tx.OTHER):
        return 60
    if focus == rc:
        return 100
    # Neighbouring disciplines share most of their fundamentals.
    near = {
        tx.POWER: {tx.ENERGY, tx.INFRASTRUCTURE, tx.INDUSTRIAL},
        tx.ENERGY: {tx.POWER, tx.POWER_ELECTRONICS},
        tx.CONTROLS: {tx.INSTRUMENTATION, tx.INDUSTRIAL},
        tx.INSTRUMENTATION: {tx.CONTROLS, tx.INDUSTRIAL},
        tx.POWER_ELECTRONICS: {tx.MACHINES, tx.ENERGY, tx.DESIGN},
        tx.MACHINES: {tx.POWER_ELECTRONICS, tx.INDUSTRIAL},
        tx.RF: {tx.EMC, tx.DESIGN},
        tx.EMC: {tx.RF, tx.DESIGN},
        tx.INFRASTRUCTURE: {tx.POWER, tx.DESIGN},
        tx.INDUSTRIAL: {tx.CONTROLS, tx.POWER, tx.MACHINES},
        tx.DESIGN: {tx.INFRASTRUCTURE, tx.POWER_ELECTRONICS},
        tx.TRANSPORT: {tx.DESIGN, tx.POWER_ELECTRONICS},
    }
    if rc in near.get(focus, set()):
        return 85
    if focus.startswith("Electrical Engineering"):
        return 70
    return 55


def compute_match(profile: dict, job: dict, lite: bool = False) -> dict:
    """job is a dict with job_title, cleaned_description, matched_keywords,
    role_category, match_score, is_candidate_friendly, eligibility_risk,
    sponsors_h1b, first_seen_at-ish freshness flag.

    lite=True returns only the scores + capped matched/missing skills — used for
    ranking the full job set fast (skips the per-job interview prep, tailoring
    suggestions, and why-matches that only the detail view needs)."""
    job_text = " ".join([
        job.get("job_title", ""), job.get("cleaned_description", "") or "",
        job.get("matched_keywords", "") or "",
    ])
    job_skills = job_skills_for(job)
    resume_skills = set(profile.get("all_skills", []))

    matched = [s for s in job_skills if s in resume_skills]
    missing = [s for s in job_skills if s not in resume_skills]

    # ── Resume-overlap sub-scores (each 0–100) ───────────────────────────────
    # 1. Skills: overlap ratio blended with absolute depth.
    if job_skills:
        overlap = len(matched) / len(job_skills)
        depth = min(1.0, len(matched) / 8)
        skills_score = round(100 * (0.5 * overlap + 0.5 * depth))
    else:
        skills_score = 45  # no parseable JD skills

    # 2. Matched projects (resume projects that touch the job's areas) + WHICH of
    #    the job's signals/skills each one backs (for the "matching projects" row).
    job_signals = [s for s, pats in PROJECT_SIGNALS.items() if any(re.search(p, job_text.lower()) for p in pats)]
    matched_projects = []
    matched_projects_detail = []
    for proj in profile.get("projects", []):
        pl = proj.lower()
        sig_backs = [s for s in job_signals if any(re.search(p, pl) for p in PROJECT_SIGNALS[s])]
        skill_backs = [m for m in matched[:8] if m.lower() in pl]
        backs = sig_backs + [m for m in skill_backs if m not in sig_backs]
        if backs:
            matched_projects.append(proj)
            matched_projects_detail.append({"title": _short_title(proj), "backs": backs[:6]})
    matched_projects = matched_projects[:4]
    # Display: prefer entries that read like real project titles (drop bullet-line
    # fragments). Score below still uses the full matched count — display only.
    _titled = [d for d in matched_projects_detail if _looks_like_title(d["title"])]
    matched_projects_detail = (_titled or matched_projects_detail)[:4]
    projects_score = [40, 70, 90, 100][min(len(matched_projects), 3)]

    # 3. Domain alignment (role category vs resume focus).
    domain_score = _domain_score(profile, job)

    # 4. Tool / protocol match — the specific tools/protocols the JD names.
    job_tools = [s for s in job_skills if s in _TOOLSET]
    matched_tools = [s for s in job_tools if s in resume_skills]
    tool_protocol_score = round(100 * len(matched_tools) / len(job_tools)) if job_tools else 60

    # ── Job-intrinsic fit scores (seniority reality, resume-independent) ──────
    lvl = job.get("experience_level", "") or ""
    is_sen = bool(job.get("is_senior"))
    ng_fit = job.get("new_grad_fit")
    if ng_fit is None:
        ng_fit = new_grad_fit_score(
            lvl, is_sen, bool(job.get("is_entry_level")),
            bool(job.get("is_candidate_friendly")), job.get("years_required_min"),
            job.get("job_title", ""), job.get("cleaned_description", ""),
        )
    exp_fit = job.get("experienced_fit")
    if exp_fit is None:
        exp_fit = experienced_fit_score(lvl, is_sen, job.get("years_required_min"))
    recommendation = overall_recommendation(ng_fit)

    # Raw résumé↔JD overlap (skills / projects / domain / tools) — no level term.
    overlap_match = round(
        0.50 * skills_score + 0.20 * projects_score
        + 0.20 * domain_score + 0.10 * tool_protocol_score
    )

    # ── Resume Match (what the user sees) = a PERSONALIZED, realistic match ──
    # Skills overlap dominates, but the role's seniority fit pulls it toward
    # reality so a Staff/Senior role can't read as a 97% match for a new-grad
    # résumé. Level fit adapts to the résumé: ranked by New Grad Fit for a
    # 0–2-yr candidate (senior roles drop), by Experienced Fit beyond that
    # (senior roles fit). This is what makes "Best Resume Match" accurate for
    # YOU rather than surfacing high-overlap roles you can't realistically get.
    yrs = profile.get("years_experience", 0) or 0
    level_fit = ng_fit if yrs < 3 else exp_fit
    resume_match = round(0.55 * overlap_match + 0.45 * level_fit)

    match_breakdown = {
        "skills": skills_score,
        "experience": ng_fit,          # "Experience / level fit" row = New Grad Fit
        "projects": projects_score,
        "domain": domain_score,
        "tool_protocol": tool_protocol_score,
    }

    # Defensibility (kept for compatibility; not shown in UI) — uses raw overlap.
    proj_factor = min(1.0, len(matched_projects) / 2)
    defensibility = round(100 * (0.55 * (overlap_match / 100) + 0.45 * proj_factor))

    # Apply priority — realistic roles for THIS candidate with a decent overlap.
    # Uses the RAW overlap (not the personalized resume_match) so level fit is not
    # double-counted. Eligibility risk only nudges.
    elig_pen = 12 if job.get("eligibility_risk") == "high" else (5 if job.get("eligibility_risk") == "medium" else 0)
    priority_score = 0.55 * level_fit + 0.45 * overlap_match - elig_pen
    apply_priority = "High" if priority_score >= 72 else ("Medium" if priority_score >= 52 else "Low")

    # Fast path for list ranking — everything the cards/sort need, none of the
    # heavy per-job detail (interview prep, suggestions, why-matches).
    if lite:
        return {
            "resume_match": resume_match,
            "new_grad_fit": ng_fit,
            "experienced_fit": exp_fit,
            "overall_recommendation": recommendation,
            "match_breakdown": match_breakdown,
            "defensibility": defensibility,
            "apply_priority": apply_priority,
            "apply_priority_score": round(priority_score, 1),
            "matched_skills": matched[:6],
            "missing_skills": missing[:6],
            "recommended_resume": _recommended_resume(job.get("role_category", ""), profile),
        }

    # Why matches
    why = []
    rc = job.get("role_category")
    if rc and rc != "Unknown":
        why.append(f"{rc} role aligned with your focus")
    if matched:
        why.append("Your skills: " + ", ".join(matched[:6]))
    if matched_projects:
        why.append(f"Backed by {len(matched_projects)} of your projects")
    if job.get("is_candidate_friendly"):
        why.append("Open to junior candidates")
    if job.get("sponsors_h1b") is True:
        why.append("Sponsors H1B")

    # Safe tailoring suggestions
    strengths = _area_strength(profile)
    suggestions = []
    for sk in missing[:10]:
        tier, rationale = _classify_suggestion(sk, profile, strengths)
        suggestions.append({"skill": sk, "tier": tier, "rationale": rationale})

    return {
        "resume_match": resume_match,
        "new_grad_fit": ng_fit,
        "experienced_fit": exp_fit,
        "overall_recommendation": recommendation,
        "match_breakdown": match_breakdown,
        "defensibility": defensibility,
        "apply_priority": apply_priority,
        "apply_priority_score": round(priority_score, 1),
        "matched_skills": matched,
        "missing_skills": missing,
        "matched_projects": matched_projects,
        "matched_projects_detail": matched_projects_detail,
        "recommended_resume": _recommended_resume(job.get("role_category", ""), profile),
        "why_matches": why,
        "tailoring_suggestions": suggestions,
        "interview_prep": _interview_prep(
            rc if rc in _INTERVIEW_TOPICS else tx.DESIGN, job_skills, profile,
            tier=job.get("company_priority", "") or "", company=job.get("company", "") or "",
        ),
    }
