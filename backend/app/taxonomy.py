"""Electrical-engineering job taxonomy — the single source of truth for Volt.

Everything domain-specific lives here: the role categories, the title rules that
assign them, the false friends that must never be mistaken for an EE posting,
and the default search terms the adapters send to each job board.

Design rules, learned the hard way on Ashborne Silicon:

* **Title first.** Many list endpoints (Workday, Eightfold, most DOM scrapes)
  return a title and nothing else, and descriptions are full of company
  boilerplate. A category decided on the title is stable; one decided on the
  body drifts with whatever the employer's template says.
* **Order matters.** The rules are tried top to bottom and the first match wins,
  so the more specific rule must come first: "Protection & Controls Engineer" is
  a Power role, and only reaches Controls if the Power rule is missing.
* **False friends are excluded before anything is accepted.** "Power BI",
  "SOX controls", "data protection", "project controls" and "electrician" all
  contain an EE word and none of them is an EE engineering job.
* **Patterns are compiled once, here, from raw strings.** Never build these
  through a shell heredoc — escapes collapse and ``\\b`` turns into a backspace
  byte that greps invisibly (that broke Ashborne Silicon's classifier once).

``tests/test_taxonomy_golden.py`` holds hand-labelled real titles; any change to
this file has to keep that set passing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Categories ────────────────────────────────────────────────────────────────
# Display order in the UI. The frontend mirrors this list in
# frontend/src/lib/categories.ts; tests/test_category_sync.py keeps them equal.

POWER = "Power Systems"
ENERGY = "Renewable Energy"
INDUSTRIAL = "Industrial & Plant"
CONTROLS = "Controls & Automation"
INSTRUMENTATION = "Instrumentation"
DESIGN = "Electrical Design"
MACHINES = "Electrical Machines"
POWER_ELECTRONICS = "Power Electronics"
RF = "RF & Communications"
EMC = "EMC / EMI"
INFRASTRUCTURE = "Buildings & Infrastructure"
TRANSPORT = "Transportation & Aerospace"
OTHER = "Other EE"          # relevant, but no category could be decided
OUT_OF_SCOPE = "Out of Scope"  # stored for audit only; never shown

CATEGORIES: tuple[str, ...] = (
    POWER, ENERGY, INDUSTRIAL, CONTROLS, INSTRUMENTATION, DESIGN, MACHINES,
    POWER_ELECTRONICS, RF, EMC, INFRASTRUCTURE, TRANSPORT,
)

# Hidden from the default view (the user can opt in). MUST equal
# HIDDEN_CATEGORIES in frontend/src/lib/categories.ts.
HIDDEN_CATEGORIES: frozenset[str] = frozenset({OTHER, OUT_OF_SCOPE, "Unknown"})

# One-line descriptions, shown as tooltips and on the companies page.
CATEGORY_BLURBS: dict[str, str] = {
    POWER: "Transmission, distribution, substations, protection & controls, grid planning, power quality, HV/HVDC, utilities",
    ENERGY: "Solar, wind, energy storage, microgrids, grid integration and interconnection, EV charging",
    INDUSTRIAL: "Plant, maintenance, reliability, field and electrical project engineering",
    CONTROLS: "Controls, PLC, SCADA, DCS, process and industrial automation",
    INSTRUMENTATION: "Instrumentation & controls (I&C), measurement, metering systems",
    DESIGN: "Electrical design, electrical systems and equipment, hardware and board-level design",
    MACHINES: "Motors, generators and rotating electrical machines, transformers",
    POWER_ELECTRONICS: "Power electronics, converters, inverters, power supplies, drives",
    RF: "RF, microwave, antennas, electromagnetics, wireless and telecom engineering",
    EMC: "EMC / EMI design, test and compliance",
    INFRASTRUCTURE: "Building/MEP electrical, data centers, critical facilities, lighting, commissioning",
    TRANSPORT: "Aerospace, aircraft, avionics, spacecraft, marine, rail, traction power, automotive/EV",
}


def _rx(*parts: str) -> re.Pattern[str]:
    """Case-insensitive alternation of raw regex fragments."""
    return re.compile("|".join(f"(?:{p})" for p in parts), re.I)


# ── Exclusions (checked first, on the TITLE) ──────────────────────────────────

# Not engineering at all, or a trade rather than an engineering role. Trades are
# real electrical careers, but this app lists engineering jobs and a lineman or
# electrician posting is noise to its audience.
EXCLUDE_NON_ENGINEERING = _rx(
    r"\bsales\b", r"\bmarketing\b", r"\brecruit", r"\bhuman resources\b", r"\bhr\b",
    r"\baccount(ant|ing)\b", r"\bfinanc(e|ial)\b", r"\bauditor?\b", r"\btax\b",
    r"\blegal\b", r"\bcounsel\b", r"\bparalegal\b", r"\battorney\b",
    r"\bprocurement\b", r"\bsourcing\b", r"\bbuyer\b", r"\bpurchasing\b",
    r"\bpayroll\b", r"\bbenefits\b", r"\btalent\b", r"\bcustomer (success|service|care)\b",
    r"\baccount (manager|executive)\b", r"\bbusiness development\b",
    r"\bprogram manager\b", r"\bproject manager\b", r"\bproduct manager\b",
    r"\boffice manager\b", r"\badministrative\b", r"\breceptionist\b",
    r"\btechnical writer\b", r"\bcommunications (specialist|manager|coordinator)\b",
    r"\bscheduler\b", r"\bplanner\b(?!.*engineer)", r"\bestimator\b",
    r"\bdispatcher\b", r"\bcoordinator\b", r"\bclerk\b", r"\bassistant\b(?!.*engineer)",
    r"\banalyst\b(?!.*engineer)", r"\bconsultant\b(?!.*engineer)",
    r"\bretail\b", r"\bstore\b", r"\bcashier\b", r"\bdriver\b", r"\bnurse\b",
    r"\bteacher\b", r"\binstructor\b", r"\bprofessor\b", r"\blecturer\b",
    r"\bartist\b", r"\bgraphic\b", r"\bux\b", r"\bui/ux\b",
    r"\bsecurity (officer|guard)\b", r"\bjanitor", r"\bcustodian\b",
)

EXCLUDE_TRADES = _rx(
    r"\belectrician\b", r"\bline\s*(man|men|worker|woman)\b", r"\blineworker\b",
    r"\bjourneyman\b", r"\bjourneyworker\b", r"\bapprentice\b", r"\bwireman\b",
    r"\btechnician\b", r"\btech\b(?!.*engineer)", r"\bmechanic\b", r"\binstaller\b",
    r"\boperator\b", r"\bforeman\b", r"\bforeperson\b", r"\bhelper\b", r"\blaborer\b",
    r"\bsplicer\b", r"\bfitter\b", r"\bwelder\b", r"\bmachinist\b", r"\bassembler\b",
    r"\binspector\b", r"\bmeter reader\b", r"\btroubleshooter\b", r"\bgroundman\b",
    r"\bdrafter\b", r"\bdraftsman\b", r"\bdraftsperson\b",
)

# Contain an EE word, are not EE engineering. The heart of Volt's precision.
EXCLUDE_FALSE_FRIENDS = _rx(
    # "Power" that is software or business
    r"\bpower\s*bi\b", r"\bpower\s*platform\b", r"\bpower\s*apps?\b",
    r"\bpower\s*automate\b", r"\bpowershell\b", r"\bpower\s*user\b",
    # "Controls" that are finance, audit, documents or scheduling
    r"\b(financial|internal|sox|it|access|document|inventory|cost|project|production|"
    r"quality|change|export|infection|pest|air traffic|credit|fraud|security)\s+controls?\b",
    r"\bcontroller\b(?!.*(engineer|plc|motor|drive|charge))",
    r"\bsox\b", r"\bcompliance (analyst|officer|specialist|manager)\b",
    # "Protection" that is not power-system protection
    r"\b(data|fire|cathodic|environmental|asset|child|revenue|loss|privacy|"
    r"consumer|information|cyber|radiation|brand|corrosion|fall|identity)\s+protection\b",
    # "Grid" / "utility" / "instrumentation" in computing
    r"\bgrid computing\b", r"\butility (software|computing|player)\b",
    # Networking and security programmes that borrow EE words.
    r"\bcontrol plane\b", r"\bdata plane\b", r"\bsdn\b", r"\bprogram protection\b",
    # "Automation" that is chip-design or test tooling, not industrial automation
    r"\b(electronic )?design automation\b", r"\btest automation\b", r"\bmaterials specialist\b",
    r"\bobservability\b", r"\btelemetry (software|platform)\b",
    # Gas and water networks also have "transmission" and "distribution".
    r"\b(natural gas|gas|pipeline|water|wastewater)\b(?!.*\belectric).*\b(transmission|distribution)\b",
    r"\b(transmission|distribution)\b.*\b(natural gas|gas main|pipeline)\b",
    # "Distribution" that is logistics
    r"\bdistribution (center|centre|warehouse|logistics|sales)\b",
    r"\bfood distribution\b", r"\bsoftware distribution\b",
    # "Lighting" in games and film
    r"\blighting (artist|director|technician)\b", r"\btechnical artist\b",
    # Wireless retail
    r"\bwireless (retail|sales|consultant|associate|advisor|store)\b",
    # IT networking that only borrows "telecom"
    r"\bnetwork (administrator|admin|engineer)\b(?!.*(rf|radio|wireless|optical|fiber|transmission))",
    r"\b(help\s*desk|desktop support|it support|service desk)\b",
)

# Other engineering disciplines. Rejected unless the title ALSO names an
# electrical signal ("Electrical & Instrumentation" is fine, "Mechanical
# Engineer" is not).
EXCLUDE_OTHER_DISCIPLINES = _rx(
    r"\bmechanical\b", r"\bcivil\b", r"\bstructural\b", r"\bchemical\b",
    r"\bgeotechnical\b", r"\benvironmental\b", r"\bhvac\b", r"\bplumbing\b",
    r"\bpiping\b", r"\bpetroleum\b", r"\breservoir\b", r"\bdrilling\b",
    r"\bbiomedical\b", r"\bindustrial hygien", r"\bsafety engineer\b",
    r"(?<!power )\bquality engineer\b", r"\bsupplier quality\b", r"\bquality assurance\b", r"\bmanufacturing engineer\b",
    r"\bprocess engineer\b", r"\bpackaging\b", r"\bmaterials? engineer\b",
    r"\btransportation (planner|engineer)\b(?!.*electric)",
    r"\btraffic engineer\b", r"\bsurvey", r"\bhydraulic",
    r"\bthermal\b", r"\bpropulsion\b", r"\bstructures\b", r"\bfluids?\b", r"\bcryogenic",
    r"\bmaterials\b",
)

# Electrical words that DO rescue an other-discipline title ("Electrical &
# Mechanical Engineer"). Deliberately excludes the generic "hardware engineer".
STRONG_ELECTRICAL = _rx(
    r"\belectrical\b", r"\belectric\b", r"\belectronics?\b(?!.*materials)", r"\bee\b",
    r"\be\s*&\s*i\b", r"\belectro[\s-]?mechanical\b", r"\bpcba?\b", r"\bavionics\b",
    r"\bpower electronics\b", r"\bcontrols?\b", r"\binstrumentation\b",
)

# Software roles. Rejected unless the title also carries a controls/power
# signal ("Controls Software Engineer", "SCADA Software Engineer" are in scope).
EXCLUDE_SOFTWARE = _rx(
    r"\bsoftware\b", r"\bsde\b", r"\bdeveloper\b", r"\bprogrammer\b(?!.*plc)",
    r"\bfront.?end\b", r"\bback.?end\b", r"\bfull.?stack\b", r"\bdevops\b",
    r"\bsite reliability\b", r"\bsre\b", r"\bdata (engineer|scientist|analyst)\b",
    r"\bmachine learning\b", r"\bml engineer\b", r"\bai engineer\b",
    r"\bcloud\b", r"\bweb\b", r"\bsalesforce\b", r"\bservicenow\b", r"\bsap\b",
    r"\bcyber", r"\binformation security\b", r"\bit (engineer|specialist|manager)\b",
    r"\bfirmware\b", r"\bembedded\b(?!.*(hardware|electrical))",
    r"\bqa engineer\b",
    r"\blinux\b", r"\bwindows\b", r"\bdatabase\b", r"\bdevsecops\b",
    r"\b(cyber|it|information|network|cloud|application|customer system|product) security\b",
    # Cyber "security engineer" — but "Security Systems Engineer" (physical
    # security / low-voltage design) is building work and stays in scope.
    r"\bsecurity engineer\b",
)

# Chip design belongs to Ashborne Silicon, not here. Board-level and power
# hardware stays in scope; IC design does not.
EXCLUDE_SEMICONDUCTOR = _rx(
    r"\brtl\b", r"\basic\b", r"\bfpga\b", r"\bvlsi\b", r"\bsoc\b", r"\bverilog\b",
    r"\bdesign verification\b", r"\bdv engineer\b", r"\bphysical design\b",
    r"\bic design\b", r"\b(analog|mixed[\s-]?signal|digital) (ic|circuit) design\b",
    r"\bcircuit design engineer\b", r"\blayout engineer\b", r"\bmask design\b",
    r"\bpost[\s-]?silicon\b", r"\bpre[\s-]?silicon\b", r"\bsilicon\b", r"\bdft\b",
    r"\bwafer\b", r"\bdevice engineer\b", r"\byield\b", r"\blithograph",
    r"\bthin film\b", r"\betch\b", r"\bcmp\b", r"\bdiffusion\b",
    r"\bdata converters?\b", r"\badc\b", r"\bdac\b", r"\bpmic\b", r"\bpower management ic\b",
    r"\bserdes\b", r"\bpll\b",
    # IC-level analog/RF design and verification, and processor silicon.
    r"\bams\b", r"\banalog mixed[\s-]signal\b", r"\brfic\b", r"\bverification engineer\b",
    r"\bcpu\b", r"\bgpu\b", r"\bsoc\b", r"\bstandard cell\b",
)

# ── Signals ───────────────────────────────────────────────────────────────────

# The title must name an engineering role. "Electrical Designer" (MEP firms) and
# "EIT"/"Engineer in Training" are included; "Specialist" and "Analyst" are not.
ENGINEERING_NOUN = _rx(
    r"\bengineer(s|ing)?\b", r"\beng\b", r"\bengr\b", r"\bdesigner\b", r"\barchitect\b",
    r"\beit\b", r"\bengineer[\s-]in[\s-]training\b", r"\bplc programmer\b",
    r"\bscientist\b(?=.*(power|grid|rf|electromagnet|antenna|energy))",
)

# Generic electrical signal: in scope, but the title alone does not say which
# category. The description decides (see classify()).
GENERIC_ELECTRICAL = _rx(
    r"\belectrical\b", r"\belectric\b", r"\belectronics?\b", r"\bee\b",
    r"\be\s*&\s*i\b", r"\belectro[\s-]?mechanical\b", r"\bhardware engineer\b", r"\belectrical hardware\b",
    r"\bboard (design|level)\b", r"\bpcb\b", r"\bpcba\b", r"\bschematic\b",
)

# Titles that are engineering but say nothing about the discipline: "Project
# Engineer", "Field Engineer", "Engineer I". These need the description to show
# real EE content before they are accepted.
AMBIGUOUS_ENGINEERING = _rx(
    r"\bproject engineer\b", r"\bfield engineer\b", r"\bdesign engineer\b",
    r"\bsystems? engineer\b", r"\btest engineer\b", r"\breliability engineer\b",
    r"\bapplications? engineer\b", r"\bcommissioning\b", r"\bstartup engineer\b",
    r"\bengineer\s+(i{1,3}|iv|[1-4])\b", r"\bassociate engineer\b",
    r"\bgraduate engineer\b", r"\bentry[\s-]level engineer\b", r"\bengineer[\s-]in[\s-]training\b",
    r"\beit\b", r"\bdevelopment engineer\b", r"\bproduct engineer\b",
    r"\bfacilities engineer\b", r"\bsite engineer\b", r"\bplant engineer\b",
    r"\bmaintenance engineer\b", r"\bservice engineer\b", r"\bstaff engineer\b",
    r"\bsenior engineer\b", r"\bprincipal engineer\b", r"\bengineering (intern|co-?op)\b",
    r"\bdesigner\b", r"\bdesign engineering\b", r"\blead engineer\b", r"\btechnical lead\b",
    r"\bengineer\b\s*$", r"^\s*engineer\b",
)

# Specific EE vocabulary used to accept an ambiguous title from its description.
# Boilerplate-proof: none of these appear in a typical employer's "about us".
EE_DESCRIPTION_TERMS: tuple[str, ...] = (
    "electrical engineering", "electrical design", "one-line", "single-line", "single line diagram",
    "switchgear", "switchboard", "panelboard", "motor control center", "mcc",
    "transformer", "substation", "relay", "protective relay", "protection and control",
    "short circuit", "arc flash", "load flow", "power flow", "coordination study",
    "grounding", "nec", "nfpa 70", "nfpa 70e", "ieee", "nema", "ul 508", "iec 61850",
    "kv", "kva", "mva", "medium voltage", "low voltage", "high voltage",
    "distribution system", "transmission line", "power system", "power distribution",
    "plc", "scada", "dcs", "hmi", "ladder logic", "studio 5000", "rslogix", "tia portal",
    "instrumentation", "p&id", "loop diagram", "control panel",
    "schematic", "pcb", "circuit", "oscilloscope", "power supply", "inverter", "converter",
    "motor", "generator", "drives", "vfd", "ups", "battery",
    "etap", "skm", "easypower", "pss/e", "psse", "pscad", "cyme", "synergi", "aspen",
    "autocad electrical", "revit", "rf", "antenna", "emc", "emi",
    "photovoltaic", "solar", "wind turbine", "energy storage", "microgrid", "interconnection",
)
EE_DESCRIPTION_MIN_HITS = 3


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern[str]


# Title rules, most specific first. First match wins.
TITLE_RULES: tuple[Rule, ...] = (
    # Transport phrases that would otherwise be read as Power ("Traction Power
    # Engineer" contains "power engineer", and belongs under Transportation).
    Rule(TRANSPORT, _rx(
        r"\btraction power\b", r"\brail electrification\b", r"\bcatenary\b",
        r"\baircraft electrical\b", r"\bspacecraft electrical\b", r"\bavionics\b", r"\bewis\b",
        r"\bhigh[\s-]voltage (harness|architecture)\b", r"\bvehicle electrical\b",
    )),
    Rule(EMC, _rx(
        r"\bemc\b", r"\bemi\b", r"\be3\b", r"electromagnetic (compatibility|interference)",
        r"\bemc/emi\b", r"\bemi/emc\b", r"\bsignal integrity\b", r"\bpower integrity\b",
    )),
    Rule(POWER, _rx(
        # Protection first, so "Protection & Controls" never reaches Controls.
        r"\bprotection\b", r"\bp\s*&\s*c\b", r"\bprotective relay", r"\brelay(ing)? (engineer|settings)\b",
        r"\bsubstations?\b", r"\btransmission\b(?!.*(rf|wireless|optical|data|fiber|calibration|gear|driveline|axle))",
        r"\bdistribution (engineer|planning|design|system|operations|automation|standards)\b",
        r"\bpower (systems?|engineer|planning|quality|delivery|system studies|flow)\b",
        r"\bgrid (engineer|planning|operations|modernization|reliability|services)\b",
        r"\bhigh[\s-]voltage\b", r"\bhvdc\b", r"\b(ehv|hv|mv)\b", r"\bmedium[\s-]voltage\b",
        r"\butility\b", r"\butilities\b", r"\bt\s*&\s*d\b", r"\bnerc\b",
        r"\boverhead (line|design)\b", r"\bunderground (design|distribution|line)\b",
        r"\binterconnection\b(?!.*(network|data))",
        r"\benergy management system\b", r"\bems engineer\b", r"\bmetering\b",
        r"\bsystem operations? engineer\b", r"\btransmission planning\b",
        r"\bstudies engineer\b", r"\bshort[\s-]circuit\b", r"\barc[\s-]flash\b",
        r"\bfacts\b", r"\bstatcom\b", r"\bswitchgear\b", r"\bgas[\s-]insulated\b", r"\bcircuit breakers?\b",
        r"\bpower (lead|design|engineering)\b",
        r"\bpower generation\b", r"\bgeneration (engineer|planning)\b", r"\bnuclear\b.*\belectrical\b",
        r"\bline design\b", r"\bderms?\b", r"\badms\b",
    )),
    Rule(ENERGY, _rx(
        r"\brenewables?\b", r"\bsolar\b", r"\bphotovoltaic\b", r"\bpv\b", r"\bwind\b",
        r"\benergy storage\b", r"\bbess\b", r"\bbattery (energy|storage|systems?)\b",
        r"\bmicrogrids?\b", r"\bgrid integration\b", r"\bder\b", r"\bdistributed energy\b",
        r"\benergy systems?\b", r"\bev charging\b", r"\bcharging (infrastructure|systems?)\b",
        r"\bhydrogen\b", r"\bfuel cell\b", r"\bgeothermal\b", r"\bhydro(electric|power)?\b",
        r"\bclean energy\b", r"\benergy engineer\b",
    )),
    Rule(INSTRUMENTATION, _rx(
        r"\binstrumentation\b", r"\bi\s*&\s*c\b", r"\bi\s*and\s*c\b", r"\binstrument (engineer|and controls)\b",
        r"\bmeasurement (engineer|systems)\b", r"\bmetrology\b", r"\bsensor (engineer|systems)\b",
        r"\banalyzer engineer\b",
    )),
    Rule(POWER_ELECTRONICS, _rx(
        r"\bpower electronics?\b", r"\bpower conversion\b", r"\bconverters?\b", r"\binverters?\b",
        r"\bpower supply\b", r"\bpower supplies\b", r"\bpsu\b", r"\bdc[\s/-]?dc\b", r"\bac[\s/-]?dc\b",
        r"\bmagnetics\b", r"\bgate driver\b", r"\bmotor drives?\b", r"\b(traction )?inverter\b",
        r"\bpower stage\b", r"\bsmps\b", r"\bups (engineer|design|systems)\b", r"\bpower hardware\b",
        r"\bpower design engineer\b", r"\bpower management\b(?!.*ic)", r"\bwide[\s-]bandgap\b",
        r"\bsic\b", r"\bgan\b", r"\bon[\s-]?board charger\b", r"\bobc\b",
    )),
    Rule(CONTROLS, _rx(
        r"\bcontrols?\b", r"\bcontrol systems?\b", r"\bautomation\b", r"\bplc\b", r"\bscada\b",
        r"\bdcs\b", r"\bhmi\b", r"\bmechatronics\b", r"\brobotics\b", r"\bmotion control\b",
        r"\bot (engineer|systems|network)\b", r"\bics engineer\b", r"\bbuilding automation\b",
        r"\bbms engineer\b", r"\bsis engineer\b", r"\bsafety instrumented\b",
    )),
    Rule(MACHINES, _rx(
        r"\bmotors?\b", r"\bgenerators?\b", r"\belectric(al)? machines?\b", r"\brotating (machines|equipment)\b",
        r"\bmachine design\b", r"\btransformers?\b", r"\bwinding\b", r"\balternator\b",
        r"\be[\s-]?machines?\b", r"\btraction motor\b",
    )),
    Rule(RF, _rx(
        r"\brf\b", r"\bradio frequency\b", r"\bmicrowave\b", r"\bmillimeter[\s-]wave\b", r"\bmmwave\b",
        r"\bantennas?\b", r"\belectromagnetics?\b", r"\bwireless\b", r"\btelecom(munications?)?\b",
        r"\bradar\b", r"\bsatcom\b", r"\bphased array\b", r"\bbeamforming\b", r"\bcommunications? engineer\b",
        r"\bcommunications? systems engineer\b", r"\bspectrum\b", r"\bradio\b",
        r"\boptical (communications?|transmission)\b", r"\bfiber (optic|network) engineer\b",
        r"\bsignal processing\b", r"\bdsp engineer\b", r"\bgnss\b", r"\bgps engineer\b",
    )),
    Rule(INFRASTRUCTURE, _rx(
        r"\bmep\b", r"\bbuilding\b", r"\bbuildings\b", r"\bdata cent(er|re)s?\b", r"\bcritical (facilities|environment|power)\b",
        r"\bmission critical\b", r"\blighting\b", r"\bcommissioning\b", r"\bfacilit(y|ies) electrical\b",
        r"\belectrical infrastructure\b", r"\binfrastructure\b", r"\bconstruction\b", r"\bhealthcare facilities\b",
        r"\bfire alarm\b", r"\blow[\s-]voltage (systems|design)\b", r"\bsecurity systems engineer\b",
    )),
    Rule(TRANSPORT, _rx(
        r"\baerospace\b", r"\baircraft\b", r"\bavionics\b", r"\bspacecraft\b", r"\bsatellite\b",
        r"\bspace\b", r"\blaunch\b", r"\bflight\b", r"\bairframe\b", r"\bewis\b",
        r"\bmarine\b", r"\bnaval\b", r"\bship(board|yard)?\b", r"\bsubmarine\b", r"\bvessel\b",
        r"\brail\b", r"\brailway\b", r"\brailroad\b", r"\btraction\b", r"\btransit\b",
        r"\blocomotive\b", r"\brolling stock\b", r"\bocs\b", r"\bcatenary\b", r"\bsignal(l)?ing (engineer|design)\b",
        r"\bautomotive\b", r"\bvehicle\b", r"\bev\b", r"\bpowertrain\b", r"\bhigh voltage battery\b",
        r"\bwire harness\b", r"\bharness\b", r"\bmissile\b", r"\buav\b", r"\bdrone\b", r"\bevtol\b",
    )),
    Rule(INDUSTRIAL, _rx(
        r"\bindustrial\b", r"\bplant\b", r"\bmaintenance\b", r"\breliability\b", r"\bfield\b",
        r"\bproject\b", r"\bmanufacturing\b", r"\bmining\b", r"\boil\b", r"\bgas\b",
        r"\brefinery\b", r"\bpetrochemical\b", r"\bpulp\b", r"\bwater\b", r"\bwastewater\b",
        r"\bfacilities\b", r"\bsite\b", r"\bstartup\b", r"\bproduction\b",
    )),
    Rule(DESIGN, _rx(
        r"\belectrical design\b", r"\belectrical systems?\b", r"\belectrical equipment\b",
        r"\belectrical hardware\b", r"\bhardware (design )?engineer\b", r"\belectronics?\b",
        r"\bboard\b", r"\bpcb\b", r"\bpcba\b", r"\bcircuit\b", r"\bschematic\b",
        r"\belectrical test\b", r"\bproduct design\b", r"\belectrical designer\b",
        r"\bwiring\b", r"\bpanel design\b",
    )),
)

# Description vocabulary for categorising a generic "Electrical Engineer" title.
# A category needs DESCRIPTION_CATEGORY_MIN_HITS distinct hits to win; otherwise
# the job falls back to Electrical Design.
DESCRIPTION_CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    POWER: ("substation", "transmission line", "distribution system", "protective relay", "relay settings",
            "protection and control", "short circuit", "load flow", "power flow", "arc flash", "coordination study",
            "utility", "nerc", "pss/e", "psse", "cyme", "synergi", "aspen oneliner", "capetool", "high voltage",
            "kv ", "power system", "grid", "interconnection", "outage", "feeder", "overhead", "underground"),
    ENERGY: ("solar", "photovoltaic", "pv ", "wind", "energy storage", "bess", "battery storage", "microgrid",
             "renewable", "inverter-based", "interconnection", "ev charging", "der "),
    INDUSTRIAL: ("plant", "maintenance", "reliability", "manufacturing", "production", "mining", "refinery",
                 "petrochemical", "root cause", "preventive maintenance", "turnaround", "outage support"),
    CONTROLS: ("plc", "scada", "dcs", "hmi", "ladder logic", "studio 5000", "rslogix", "tia portal",
               "ignition", "wonderware", "control system", "automation", "process control", "loop tuning", "pid"),
    INSTRUMENTATION: ("instrumentation", "i&c", "p&id", "loop diagram", "transmitter", "analyzer", "calibration",
                      "flow meter", "isa ", "instrument index"),
    DESIGN: ("schematic", "pcb", "circuit", "altium", "orcad", "cadence allegro", "board", "power distribution",
             "autocad electrical", "electrical design", "wiring diagram", "panel"),
    MACHINES: ("motor", "generator", "rotating", "winding", "stator", "rotor", "electric machine", "transformer design"),
    POWER_ELECTRONICS: ("power electronics", "converter", "inverter", "dc-dc", "ac-dc", "gate driver", "magnetics",
                        "plecs", "ltspice", "sic", "gan", "switching", "power stage", "motor drive"),
    RF: ("rf ", "microwave", "antenna", "hfss", "cst", "ads ", "keysight", "vna", "spectrum analyzer", "wireless",
         "lte", "5g", "radar", "link budget", "electromagnetic"),
    EMC: ("emc", "emi", "radiated emissions", "conducted emissions", "immunity", "cispr", "fcc part 15",
          "mil-std-461", "do-160"),
    INFRASTRUCTURE: ("building", "mep", "data center", "lighting", "revit", "commissioning", "critical facilities",
                     "nec", "construction documents", "life safety", "fire alarm"),
    TRANSPORT: ("aircraft", "avionics", "aerospace", "do-178", "do-254", "spacecraft", "satellite", "rail",
                "traction", "vehicle", "automotive", "marine", "naval", "harness"),
}
DESCRIPTION_CATEGORY_MIN_HITS = 2


# ── Seniority vocabulary (title-level) ────────────────────────────────────────
# Utilities and EPC firms grade engineers I–IV and use EIT / PE as rank markers.

INTERN_TITLE = re.compile(r"\b(intern(ship)?|co-?op|summer (student|associate))\b", re.I)
NEW_GRAD_TITLE = re.compile(
    r"\b(new\s+grad(uate)?|new\s+college\s+grad|recent\s+graduate|university\s+grad(uate)?|"
    r"early\s+career|campus|graduate (engineer|program)|rotational|development program|"
    r"engineer[\s-]in[\s-]training|\beit\b|associate engineer|engineer\s+(i|1)\b|level\s+(i|1)\b|"
    r"junior|jr\.?|entry[\s-]level)\b", re.I)
MID_TITLE = re.compile(r"\b(engineer\s+(ii|2)|level\s+(ii|2))\b", re.I)
# A grade range that starts at entry: "I, II, III", "I/II", "1-3", "(Entry, Staff…)".
MULTI_GRADE_ENTRY = re.compile(
    r"\b(i|1)\s*(,|/|-|–|or|&|and)\s*(?:[a-z]+\s+){0,2}(ii|2)\b"
    r"|\b(engineer|level|designer)\s+(i|1)\s*(,|/|or|&|and)\s*(senior|sr\.?|staff|lead|principal)\b"
    r"|\(\s*entry\b|\bentry\s*(,|/|or)\s*(staff|senior|associate|intermediate|mid)"
    r"|\b(associate|junior|entry[\s-]level)\s*(or|/)\s*(staff|senior|intermediate|mid)",
    re.I,
)
SENIOR_GRADE_TITLE = re.compile(r"\b(engineer\s+(iii|iv|3|4)|level\s+(iii|iv|3|4))\b", re.I)


# ── Requirement tags (badges) ─────────────────────────────────────────────────
# Shown on cards so a candidate sees the gate before clicking Apply.

REQUIREMENT_TAGS: dict[str, tuple[str, ...]] = {
    "PE license": (
        r"\bp\.?e\.?\s+licen[sc]e", r"professional engineer(ing)? licen[sc]e", r"licensed professional engineer",
        r"\bpe\b (is )?required", r"registered professional engineer", r"\bp\.?e\.? registration",
        r"ability to obtain (a |your )?\bp\.?e\b",
    ),
    "EIT / FE": (
        r"engineer[\s-]in[\s-]training", r"\beit\b", r"\bfe exam\b", r"fundamentals of engineering",
        r"\be\.?i\.?t\.? certification",
    ),
    "NERC": (r"\bnerc\b",),
    "Clearance": (
        r"security clearance", r"secret clearance", r"top secret", r"ts/sci", r"active clearance",
        r"\bdod clearance\b", r"ability to obtain (a |and maintain )?(security )?clearance",
    ),
    "Travel": (
        r"travel (up to )?\d{1,2}\s?%", r"\d{1,2}\s?% travel", r"willing(ness)? to travel",
        r"extensive travel", r"overnight travel",
    ),
    "On-call / storm duty": (
        r"on[\s-]call", r"storm (duty|restoration|response)", r"emergency restoration", r"24/7 (support|response)",
    ),
}
_REQUIREMENT_RX = {tag: _rx(*pats) for tag, pats in REQUIREMENT_TAGS.items()}


def requirement_tags(text: str) -> list[str]:
    """Badges for a posting's gating requirements, in display order."""
    t = text or ""
    return [tag for tag, rx in _REQUIREMENT_RX.items() if rx.search(t)]


# ── Default search terms per adapter ──────────────────────────────────────────
# Sent to each job board's own search. Broad on purpose — precision is the
# classifier's job, recall is this list's. Ordered by yield: the adapters cap how
# many terms they send, so the most productive term must come first.

DEFAULT_SEARCH_TERMS: tuple[str, ...] = (
    "electrical engineer",
    "power systems",
    "controls engineer",
    "protection",
    "substation",
    "instrumentation",
    "power electronics",
    "RF engineer",
    "automation engineer",
    "electrical design",
)


# ── Classification ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Verdict:
    relevant: bool
    category: str
    reason: str
    # True when the title alone could not decide and the description did.
    needs_description: bool = False


_TERM_RX: dict[str, re.Pattern[str]] = {}


def _term_rx(term: str) -> re.Pattern[str]:
    """Whole-word matcher for a vocabulary term. Plain substring tests counted
    "nec" in "connect", "emi" in "semiconductor", "ups" in "groups" and "rf" in
    "performance" — inflating the evidence used to accept ambiguous titles."""
    rx = _TERM_RX.get(term)
    if rx is None:
        rx = re.compile(r"(?<![a-z0-9])" + re.escape(term.strip()) + r"(?![a-z0-9])")
        _TERM_RX[term] = rx
    return rx


def term_hits(text: str, terms: tuple[str, ...]) -> list[str]:
    """Distinct vocabulary terms present in already-lowercased text, whole words only."""
    return [t for t in dict.fromkeys(terms) if _term_rx(t).search(text)]


def _count_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return term_hits(text, terms)


def category_from_description(description: str) -> str | None:
    """Best category for a generic EE title, or None if the body is too thin."""
    d = f" {(description or '').lower()} "
    best, best_hits = None, 0
    for cat, terms in DESCRIPTION_CATEGORY_TERMS.items():
        hits = len(_count_terms(d, terms))
        if hits > best_hits:
            best, best_hits = cat, hits
    return best if best_hits >= DESCRIPTION_CATEGORY_MIN_HITS else None


def title_category(title: str) -> str | None:
    for rule in TITLE_RULES:
        if rule.pattern.search(title):
            return rule.category
    return None


def classify(title: str, description: str = "") -> Verdict:
    """Decide whether a posting is an EE engineering job, and which category.

    Title-first. The description is consulted only to (a) accept a title that is
    engineering but discipline-free ("Project Engineer") and (b) pick a category
    for a generic "Electrical Engineer". It is never allowed to override a
    decisive title in either direction.
    """
    t = " ".join((title or "").split())
    d = (description or "").lower()

    if not t:
        return Verdict(False, OUT_OF_SCOPE, "No title")

    has_electrical = bool(GENERIC_ELECTRICAL.search(t))
    cat = title_category(t)
    # A title that names a power/controls signal is allowed through the software
    # filter ("SCADA Software Engineer", "Controls Software Engineer").
    # "automation" is deliberately NOT here: "Software Engineer (Test & Automation)"
    # and "Machine Learning Automation Engineer" are software roles.
    domain_software = bool(re.search(
        r"\b(controls?|plc|scada|dcs|hmi|protection|relay)\b", t, re.I))

    if EXCLUDE_FALSE_FRIENDS.search(t):
        return Verdict(False, OUT_OF_SCOPE, "False friend (EE word, non-EE role)")
    if EXCLUDE_NON_ENGINEERING.search(t):
        return Verdict(False, OUT_OF_SCOPE, "Non-engineering role")
    # "Engineering Technician" is a technician: only the noun "engineer" rescues.
    if EXCLUDE_TRADES.search(t) and not re.search(r"\bengineers?\b", t, re.I):
        return Verdict(False, OUT_OF_SCOPE, "Trade / technician role")
    # Chip vocabulary never appears in grid, plant or building titles, so those
    # categories are exempt ("Substation Physical Design Engineer" is a power job).
    if EXCLUDE_SEMICONDUCTOR.search(t) and cat not in (POWER, ENERGY, INDUSTRIAL, INFRASTRUCTURE):
        return Verdict(False, OUT_OF_SCOPE, "Chip design (out of EE-jobs scope)")
    if EXCLUDE_SOFTWARE.search(t) and not domain_software:
        return Verdict(False, OUT_OF_SCOPE, "Software role")
    # "Civil Engineer - Substations" names a power word but is civil work. The
    # generic "hardware engineer" signal does not rescue a mechanical title
    # ("Passive Thermal Hardware Engineer"); a genuinely electrical word does.
    if EXCLUDE_OTHER_DISCIPLINES.search(t) and not STRONG_ELECTRICAL.search(t):
        return Verdict(False, OUT_OF_SCOPE, "Other engineering discipline")
    if not ENGINEERING_NOUN.search(t):
        return Verdict(False, OUT_OF_SCOPE, "Not an engineering title")

    # A specific category rule hit. Industrial is the weakest rule ("project",
    # "field", "site"…), so it only counts when the title is also electrical.
    if cat and cat != INDUSTRIAL and cat != DESIGN:
        if cat == TRANSPORT and not has_electrical and not re.search(
                r"\b(avionics|ewis|harness|traction|catenary|ocs|electric|power|high voltage|ev\b)", t, re.I):
            # "Aerospace Engineer", "Flight Test Engineer" — usually mechanical or
            # systems work. Accept only if the body is clearly electrical.
            return _from_description(d, TRANSPORT, "Transportation title, electrical body")
        if cat == INFRASTRUCTURE and not has_electrical and not re.search(
                r"\b(data cent|critical|lighting|mep|fire alarm|low[\s-]voltage)", t, re.I):
            return _from_description(d, INFRASTRUCTURE, "Infrastructure title, electrical body")
        return Verdict(True, cat, f"Title rule: {cat}")

    if has_electrical or cat in (INDUSTRIAL, DESIGN):
        if cat == INDUSTRIAL and not has_electrical:
            # "Project Engineer", "Field Engineer": the body names the discipline,
            # and usually the category too (a substation project is Power work).
            return _from_description(d, None, "Industrial title, electrical body", default=INDUSTRIAL)
        if cat == DESIGN or cat is None:
            by_body = category_from_description(d)
            if cat is None and by_body:
                return Verdict(True, by_body, "Electrical title, category from description", True)
            return Verdict(True, DESIGN if cat in (DESIGN, None) else cat,
                           "Electrical title" + (", generic" if cat is None else ""))
        # Electrical + Industrial ("Plant Electrical Engineer")
        return Verdict(True, INDUSTRIAL, "Title rule: Industrial (electrical)")

    if AMBIGUOUS_ENGINEERING.search(t):
        return _from_description(d, None, "Discipline-free title, electrical body")

    return Verdict(False, OUT_OF_SCOPE, "No EE signal in title")


def _from_description(desc_l: str, fixed: str | None, reason: str, default: str = OTHER) -> Verdict:
    """Accept a title only when its description is unmistakably EE work.

    ``fixed`` pins the category (the title already decided it); otherwise the
    description picks one, falling back to ``default``.
    """
    if not desc_l:
        return Verdict(False, fixed or default, "Needs description to decide", True)
    hits = _count_terms(f" {desc_l} ", EE_DESCRIPTION_TERMS)
    if len(set(hits)) < EE_DESCRIPTION_MIN_HITS:
        return Verdict(False, fixed or default, f"Too few EE terms in description ({len(set(hits))})", True)
    cat = fixed or category_from_description(desc_l) or default
    return Verdict(True, cat, reason, True)
